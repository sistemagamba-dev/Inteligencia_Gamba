"""Interface do protótipo: uma tabela, uma aprovação. Ambiente definido pela equipe técnica."""
from io import BytesIO
import time

import pandas as pd
import streamlit as st
import runtime
from acesso import Refused
from experiments.sheets_poc.store import Busy as SheetsBusy, Unconfirmed
from storage import Busy
from workflow import EDITABLE

BUSY = (Busy, SheetsBusy)
UNCONFIRMED = ('Gravação não confirmada. Clique novamente em “Aprovar e registrar tudo”; '
               'nada será registrado em duplicidade.')

LABELS = {'protocol': 'PROTOCOLO', 'requester': 'Solicitante', 'created': 'Data do Envio',
          'category': 'ENQUADRAMENTO', 'address': 'ENDEREÇO',
          'description': 'OCORRÊNCIA- Descrição sintética do pedido', 'neighborhood': 'BAIRRO'}
AUTH_TTL = 30  # Segundos: edições da tabela não consultam o cadastro a cada clique.
SESSION = ('batch', 'result', 'export', 'pending', 'auth', 'adm', 'adm_msg')
PASTA = {'ok': 'compartilhada', 'ausente': 'sem acesso', 'herdada': 'acesso herdado (avise a equipe técnica)'}


@st.cache_resource(show_spinner=False)
def access_components():
    # Só credencial + cadastro: basta para autorizar; Drive e journal ficam para depois.
    return runtime.access_components()


@st.cache_resource(show_spinner=False)
def components(_access=None):
    # Um fluxo por processo: o lock contra clique duplo é compartilhado entre as sessões.
    return runtime.components(_access)


def forget():
    for key in SESSION:
        st.session_state.pop(key, None)


def authorized(access, email, fresh=False):
    cached = st.session_state.get('auth')
    if not fresh and cached and cached[0] == email and time.monotonic() - cached[1] < AUTH_TTL:
        return True
    if access.is_authorized(email):
        st.session_state.auth = (email, time.monotonic())
        return True
    forget()
    return False


def guard(access, email, admin=False):
    """Conferência atual antes de cada ação sensível: sessão aberta não age depois da remoção."""
    if access is None:
        return  # Demonstração local.
    if not (authorized(access, email, fresh=True) and (not admin or access.is_admin(email))):
        blocked()


def blocked():
    forget()
    st.error('Seu acesso foi removido.')
    st.button('Sair', on_click=st.logout, key='sair_removido')
    st.stop()


def load_status(access, email):
    try:
        st.session_state.adm = access.status(email)
    except PermissionError:
        raise
    except Exception:
        st.session_state.adm = {'erro': True}


def adm_action(access, email, call):
    guard(access, email, admin=True)
    try:
        result = call()
        ok = all(v for v in result.values() if isinstance(v, bool))
        st.session_state.adm_msg = (ok, result['mensagem'])
    except PermissionError:
        blocked()
    except Refused as exc:
        st.session_state.adm_msg = (False, str(exc))
    except Exception:
        st.session_state.adm_msg = (False, 'Não foi possível concluir. Tente novamente.')
    load_status(access, email)
    st.rerun()


def adm(access, email):
    """Só para administradores da configuração; cada ação confere de novo."""
    pastas = {'entrada': 'de entrada', 'raiz': 'raiz (vale para processados, falhas e tudo que estiver nela)'}
    papeis = {'reader': 'leitor', 'commenter': 'comentarista', 'writer': 'editor',
              'fileorganizer': 'organizador', 'organizer': 'administrador', 'owner': 'proprietário'}

    def amplo(item):
        tipo, alvo = item.get('tipo'), item.get('alvo') or '?'
        quem = {'anyone': 'qualquer pessoa com o link', 'domain': f'domínio {alvo}',
                'group': f'grupo {alvo}'}.get(tipo, f'permissão do tipo {tipo} ({alvo})')
        return (f"Compartilhamento amplo na pasta {pastas.get(item.get('onde'), 'desconhecida')}: {quem} "
                f"({papeis.get(item.get('papel'), item.get('papel') or '?')}) — revise no Google Drive.")

    with st.expander('Adm'):
        if 'adm' not in st.session_state:
            load_status(access, email)
        message = st.session_state.get('adm_msg')
        if message:
            (st.success if message[0] else st.warning)(message[1])
        address = st.text_input('E-mail Google do assessor', key='adm_email')
        if st.button('Adicionar'):
            adm_action(access, email, lambda: access.add(email, address))
        status = st.session_state.adm
        if status.get('erro'):
            st.error('Não foi possível consultar o cadastro ou a pasta agora. Tente novamente.')
        else:
            broad = status.get('amplos')
            isolated = status.get('isolamento_ok') is True and broad == []
            if not isolated:
                # Nunca há botão aqui: compartilhamento amplo não é do JANUS e exige revisão humana.
                lines = [amplo(b) for b in broad or ()]
                st.error('\n\n'.join(lines) or 'Não foi possível confirmar que a pasta de entrada e a raiz '
                         'não têm compartilhamento amplo. Use “Atualizar lista” ou revise no Google Drive.')
            if status['compartilhamento'] and isolated:
                st.caption('Pasta de entrada: compartilhamento disponível.')
            elif not status['compartilhamento']:
                st.warning('A conta técnica não tem permissão para compartilhar a pasta de entrada. '
                           'Avise a equipe técnica.')
            st.markdown('**Assessores com acesso**')
            if not status['usuarios']:
                st.caption('Nenhum assessor cadastrado.')
            for user in status['usuarios']:
                left, right = st.columns([4, 1])
                left.write(f"{user['email']} · JANUS: liberado · Pasta: {PASTA[user['pasta']]}")
                if right.button('Remover', key='remover_' + user['email']):
                    adm_action(access, email, lambda u=user['email']: access.remove(email, u))
            if status['pendencias']:
                st.markdown('**Pendências na pasta de entrada**')
                st.caption('Têm permissão na pasta, mas não acessam o JANUS. Revogue se não deveriam ter.')
                for orphan in status['pendencias']:
                    left, right = st.columns([4, 1])
                    left.write(orphan)
                    if right.button('Revogar', key='revogar_' + orphan):
                        adm_action(access, email, lambda o=orphan: access.revoke_orphan(email, o))
        if st.button('Atualizar lista'):
            guard(access, email, admin=True)
            load_status(access, email)
            st.rerun()


def main():
    st.set_page_config(page_title='JANUS | Inteligência Gambá', page_icon='📄', layout='wide')
    try:
        producao = runtime.producao()
    except ValueError:
        st.error('Configuração inválida. Solicite à equipe técnica a revisão da configuração.')
        return
    st.caption('INTELIGÊNCIA GAMBÁ  /  ' + ('OPERAÇÃO' if producao else 'AMBIENTE DE TESTE'))
    st.title('Protocolos JANUS')
    st.write('Coloque os PDFs na pasta de entrada. Processe, confira e aprove o lote para registrar.')
    if runtime.mode() == 'google' and not getattr(st.user, 'is_logged_in', False):
        # Login Google do próprio Streamlit ([auth] nos segredos); sem login, nada é carregado.
        try:
            configured = 'auth' in st.secrets
        except Exception:
            configured = False
        if configured:
            st.button('Entrar com Google', type='primary', on_click=st.login)
        else:
            st.error('O acesso ainda não foi configurado. Solicite à equipe técnica.')
        return
    unavailable = (('O sistema' if producao else 'O ambiente de teste') +
                   ' está indisponível. Solicite à equipe técnica a revisão da configuração.')
    access, email = None, None
    if runtime.mode() == 'google':
        # Autorização atual (configuração + cadastro) antes de qualquer recurso privado (Drive, journal).
        try:
            access, email = access_components(), getattr(st.user, 'email', None)
        except Exception:
            st.error(unavailable)
            return
        if access is None or not authorized(access, email):
            forget()
            st.error('Acesso não autorizado. Entre com a conta indicada pela equipe técnica.')
            st.button('Sair', on_click=st.logout)
            return
    try:
        flow = components(access)
    except Exception:
        st.error(unavailable)
        return
    drive = flow.drive
    if hasattr(drive, 'entrada'):
        st.link_button('Abrir pasta de entrada', 'https://drive.google.com/drive/folders/' + drive.entrada)
    elif not producao:
        st.info('Demonstração com PDFs inventados. Nenhum dado do gabinete é utilizado.')
    if st.button('Processar PDFs', type='primary'):
        guard(access, email)
        try:
            with st.spinner('Lendo os PDFs da pasta de entrada…'):
                st.session_state.batch = flow.process()
                st.session_state.pending = len(st.session_state.batch['recovery']['archive_failures'])
                st.session_state.pop('result', None)
                st.session_state.pop('export', None)
        except BUSY as exc:
            st.warning(str(exc))
        except ValueError as exc:
            st.error(str(exc) if str(exc).startswith('A base ainda') else
                     'Não foi possível acessar a pasta. Tente novamente ou avise a equipe técnica.')
        except Exception:
            st.error('Não foi possível acessar a pasta. Tente novamente ou avise a equipe técnica.')
    batch = st.session_state.get('batch')
    result = st.session_state.get('result')
    if batch and not result:
        st.subheader('Confira o lote')
        st.write(f"Encontrados: {batch['found']} · Novos para conferir: {len(batch['rows'])} · "
                 f"Duplicados ignorados: {len(batch['duplicates'])} · Falhas de leitura: {len(batch['failures'])}")
        if batch['duplicates']:
            st.info('Os duplicados foram ignorados e continuam na entrada para consulta. O histórico foi preservado.')
            st.dataframe(pd.DataFrame(batch['duplicates']).rename(columns={'alias':'Arquivo','url':'PDF'}),
                hide_index=True, column_config={'PDF': st.column_config.LinkColumn('PDF', display_text='Abrir PDF')})
        for failure in batch['failures']:
            st.warning(f"{failure['alias']}: {failure['message']}")
            if failure['url']:
                st.link_button('Conferir ' + failure['alias'], failure['url'])
        if batch['recovery']['archive_failures']:
            st.warning('Há PDFs já registrados com arquivamento pendente. Use “Tentar arquivar novamente”.')
        if batch['rows']:
            st.caption('A coluna Atenção destaca em amarelo campos ausentes ou a revisar. '
                       'Campos opcionais podem ficar em branco; o protocolo precisa ser válido. '
                       'Data do Envio: ano-mês-dia, extraída da criação do PDF.')
            rows = []
            for source in batch['rows']:
                record = source['record']
                issues = ['Confira ' + LABELS[f] for f in EDITABLE if not record[f]]
                if 'tipo_nao_suportado_revisar' in record['warnings']:
                    issues.append('Tipo não reconhecido: preencha os campos consultando o PDF')
                if 'bairro_ambiguo_revisar' in record['warnings']:
                    issues.append('Endereço/bairro ambíguo: confira no PDF')
                rows.append({'Arquivo': source['alias'], 'PDF': source['url'],
                             'Atenção': '; '.join(issues),
                             **{LABELS[f]: record[f] for f in EDITABLE}, 'Endereço original': record['full_address']})
            frame = pd.DataFrame(rows)
            styled = frame.style.map(lambda v: 'background-color: #fff2c6; color: #403300' if v else '',
                                     subset=['Atenção'])
            edited = st.data_editor(styled, hide_index=True, num_rows='fixed',
                disabled=['Arquivo', 'PDF', 'Atenção', 'Endereço original'],
                column_config={'PDF': st.column_config.LinkColumn('PDF', display_text='Abrir PDF')},
                key='table_' + batch['id'], width='stretch')
            edits = [{f: row[LABELS[f]] for f in EDITABLE} for row in edited.to_dict('records')]
            if st.button('Aprovar e registrar tudo', type='primary'):
                guard(access, email)
                try:
                    with st.spinner('Registrando o lote e arquivando os PDFs…'):
                        st.session_state.result = flow.approve(batch, edits, approved=True)
                        st.session_state.pending = len(st.session_state.result['archive_failures'])
                        st.session_state.pop('export', None)
                    st.rerun()
                except BUSY as exc:
                    st.warning(str(exc))
                except Unconfirmed:
                    st.warning(UNCONFIRMED)
                except ValueError as exc:
                    # Somente validações internas conhecidas, sem mensagens do provedor.
                    known = ('Confira o número', 'Confira a data', 'Um PDF mudou', 'A tabela mudou')
                    st.error(str(exc) if str(exc).startswith(known) else
                             'Não foi possível concluir. Processe novamente; os registros confirmados serão preservados.')
                except Exception:
                    st.error('Não foi possível concluir. Processe novamente; os registros confirmados serão preservados.')
            if not hasattr(drive, 'entrada') and not producao:
                with st.expander('Consultar PDFs de demonstração'):
                    for source in batch['rows']:
                        try:
                            st.download_button(source['alias'], drive.read(source['file_id']),
                                file_name=source['alias']+'.pdf', mime='application/pdf', key=source['file_id'])
                        except Exception:
                            st.caption('PDF já arquivado ou indisponível.')
        elif not batch['found']:
            st.info('A pasta de entrada está vazia. Adicione PDFs e clique em Processar PDFs.')
    if result:
        st.success(f"Lote concluído: {result['inserted']} novos registrados; {result['ignored']} duplicados ignorados; "
                   f"{result['failures']} falhas de leitura; {len(result['archive_failures'])} arquivamentos pendentes.")
    if 'pending' not in st.session_state:
        # Uma leitura por sessão; as edições da tabela não consultam o Sheets.
        try:
            st.session_state.pending = len(flow.pending_archives())
        except Exception:
            st.session_state.pending = 0  # Leitura indisponível; Processar PDFs tenta de novo.
    pending = st.session_state.pending
    if pending:
        st.warning(f'{pending} PDF(s) registrado(s) aguardam arquivamento. Não é necessário aprovar novamente.')
        if st.button('Tentar arquivar novamente'):
            guard(access, email)
            try:
                response = flow.resume()
                st.session_state.pending = len(response['archive_failures'])
                st.info(f"Arquivados agora: {response['archived']}. Pendentes: {len(response['archive_failures'])}.")
            except BUSY as exc:
                st.warning(str(exc))
            except Exception:
                st.error('Não foi possível arquivar agora. Tente novamente em instantes.')
    st.divider()
    if st.button('Preparar Excel da base'):
        guard(access, email)
        try:
            target = BytesIO()
            flow.export(target)
            st.session_state.export = target.getvalue()
        except Exception:
            st.error('Não foi possível preparar o Excel. Tente novamente.')
    if 'export' in st.session_state:
        if access is not None and not authorized(access, email, fresh=True):
            blocked()  # Excel já preparado não é entregue a quem perdeu o acesso.
        data = st.session_state.export

        def excel():
            # Chamada pelo Streamlit no clique, com o cadastro relido agora: o botão já desenhado não
            # entrega o Excel a quem foi removido depois. (Bytes diretos ficariam numa URL /media
            # servida sem rerun nem conferência.)
            if access is not None and not access.is_authorized(email):
                raise PermissionError('Seu acesso foi removido.')
            return data
        st.download_button('Baixar Excel (.xlsx)', excel,
            file_name='JANUS.xlsx' if producao else 'JANUS-teste.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if access is not None and access.is_admin(email):
        adm(access, email)


if __name__ == '__main__':
    main()
