"""Autorização e Adm: cadastro (aba usuarios) + permissão direta na pasta entrada.

Administradores vêm só da configuração: o cadastro nunca promove ninguém.
Toda falha de leitura nega acesso; nenhum resultado é informado sem confirmação das duas etapas.
"""
import re
import threading

LOCK = threading.Lock()  # Mudanças de ACL da entrada em sequência, para todo o processo.
EMAIL = re.compile(r'[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+')

SHARE_FAILED = 'Não foi possível compartilhar a pasta de entrada. Nada foi liberado.'
NO_SHARE = 'A conta técnica não tem permissão para compartilhar a pasta de entrada. Nada foi liberado.'
NOT_REGISTERED = ('Pasta compartilhada, mas o acesso ao JANUS não foi registrado. '
                  'Tente adicionar novamente ou remova.')
UNCERTAIN = ('Não foi possível confirmar o compartilhamento da pasta. O acesso ao JANUS não foi liberado; '
             'confira as Pendências e use “Revogar” se o e-mail aparecer lá.')
# Recusas do Drive anteriores a qualquer escrita: nesses casos nada foi compartilhado.
BEFORE_WRITE = ('E-mail inválido', 'Conta proprietária', 'Conta técnica sem permissão', 'Acesso herdado')
ADDED = 'Acesso liberado ao JANUS e à pasta de entrada.'
NOT_BLOCKED = 'Não foi possível bloquear; nada mudou. Tente novamente.'
NOT_REVOKED = ('Acesso ao JANUS bloqueado, mas a permissão na pasta continua. '
               'Use “Revogar” na lista de pendências.')
REMOVED = 'Acesso removido do JANUS e da pasta de entrada.'


class Refused(ValueError):
    """Pedido recusado com mensagem própria, segura para mostrar na tela."""


def normalize_email(value):
    email = value.strip().lower() if isinstance(value, str) else ''
    if not EMAIL.fullmatch(email):
        raise Refused('E-mail inválido')
    return email


def _plain(value):
    return str(value or '').strip().lower()


class AccessManager:
    def __init__(self, registry, drive, *, admins, allowed=(), protected=(), lock=None):
        self.registry, self.drive, self.lock = registry, drive, lock or LOCK
        self.admins = frozenset(normalize_email(e) for e in admins)
        self.allowed = frozenset(_plain(e) for e in allowed if _plain(e))
        self.protected = frozenset(_plain(e) for e in protected if _plain(e))

    def is_admin(self, email):
        try:
            return normalize_email(email) in self.admins
        except ValueError:
            return False

    def is_authorized(self, email):
        try:
            email = normalize_email(email)
            if email in self.admins or email in self.allowed:
                return True
            return email in {_plain(e) for e in self.registry.active()}  # Leitura atual a cada chamada.
        except Exception:
            return False

    def _admin(self, admin):
        if not self.is_admin(admin):
            raise PermissionError('Acesso restrito ao administrador.')
        return normalize_email(admin)

    def _owners(self, sharing):
        return {_plain(e) for e in sharing.get('owners') or ()}

    def _refuse(self, email, owners=(), static=False):
        if email in self.admins:
            raise Refused('Administradores são definidos pela equipe técnica e não podem ser alterados aqui.')
        if email in self.protected or email in owners:
            raise Refused('Esta conta é do sistema e não pode ser alterada aqui.')
        if static and email in self.allowed:
            raise Refused('Este acesso é definido pela equipe técnica e não pode ser alterado aqui.')

    def _sharing_owners(self):
        try:
            return self._owners(self.drive.entrada_sharing())
        except Exception:
            return set()  # Drive recusa remover proprietário de qualquer forma.

    def add(self, admin, email):
        admin, email = self._admin(admin), normalize_email(email)
        self._refuse(email)
        result = lambda app, pasta, mensagem: {'email': email, 'app': app, 'pasta': pasta, 'mensagem': mensagem}
        with self.lock:
            try:
                sharing = self.drive.entrada_sharing()
            except Exception:
                return result(False, False, SHARE_FAILED)
            self._refuse(email, self._owners(sharing))
            if not sharing.get('can_share'):
                return result(False, False, NO_SHARE)
            try:
                permission = self.drive.share_entrada(email)
            except Exception as exc:
                # Depois de tentar a escrita, a permissão pode existir sem confirmação.
                before = isinstance(exc, ValueError) and str(exc).startswith(BEFORE_WRITE)
                return result(False, False, SHARE_FAILED if before else UNCERTAIN)
            try:
                self.registry.add(email, by=admin, permission_id=permission or '')
            except Exception:
                return result(False, True, NOT_REGISTERED)
            return result(True, True, ADDED)

    def remove(self, admin, email):
        admin, email = self._admin(admin), normalize_email(email)
        self._refuse(email, static=True)
        result = lambda app, pasta, mensagem: {'email': email, 'app_bloqueado': app,
                                               'pasta_revogada': pasta, 'mensagem': mensagem}
        with self.lock:
            self._refuse(email, self._sharing_owners())
            try:
                self.registry.remove(email, by=admin)  # Primeiro bloqueia o app.
            except Exception:
                return result(False, False, NOT_BLOCKED)
            try:
                self.drive.revoke_entrada(email)
            except Exception:
                return result(True, False, NOT_REVOKED)
            return result(True, True, REMOVED)

    def status(self, admin):
        self._admin(admin)
        sharing = self.drive.entrada_sharing()
        permissions = self.drive.entrada_permissions()
        # Compartilhamento amplo (link, domínio, grupo, tipo desconhecido) na entrada ou na raiz:
        # só é mostrado, nunca revogado aqui (não foi o JANUS que criou; exige revisão humana).
        broad = list(self.drive.broad_sharing())
        permissions = [p for p in permissions if p.get('type') == 'user']
        active = sorted({_plain(e) for e in self.registry.active()})
        direct, inherited = set(), set()
        for p in permissions:
            (inherited if p.get('inherited') else direct).add(_plain(p.get('email')))
        users = [{'email': e, 'app': True,
                  'pasta': 'ok' if e in direct else 'herdada' if e in inherited else 'ausente'} for e in active]
        skip = set(active) | self.protected | self._owners(sharing) | self.admins | self.allowed | {''}
        orphans = sorted({_plain(p.get('email')) for p in permissions
                          if not p.get('inherited') and p.get('role') != 'owner'} - skip)
        return {'compartilhamento': bool(sharing.get('can_share')), 'usuarios': users, 'pendencias': orphans,
                'amplos': broad, 'isolamento_ok': not broad}

    def revoke_orphan(self, admin, email):
        self._admin(admin)
        email = normalize_email(email)
        self._refuse(email, static=True)
        result = lambda ok, mensagem: {'email': email, 'pasta_revogada': ok, 'mensagem': mensagem}
        with self.lock:
            self._refuse(email, self._sharing_owners())
            try:
                active = {_plain(e) for e in self.registry.active()}
            except Exception:
                return result(False, 'Não foi possível conferir o cadastro; nada mudou. Tente novamente.')
            if email in active:
                raise Refused('Este e-mail tem acesso ao JANUS. Use “Remover”.')
            try:
                self.drive.revoke_entrada(email)
            except Exception:
                return result(False, 'Não foi possível revogar a permissão na pasta. Tente novamente.')
            return result(True, 'Permissão na pasta revogada.')
