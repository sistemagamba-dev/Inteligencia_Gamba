"""Interface do protótipo: uma tabela, uma aprovação. Apenas ambiente de teste."""
from io import BytesIO

import pandas as pd
import streamlit as st
import runtime
from experiments.sheets_poc.store import Busy as SheetsBusy, Unconfirmed
from storage import Busy
from workflow import EDITABLE

BUSY = (Busy, SheetsBusy)
UNCONFIRMED = ('Gravação não confirmada. Clique novamente em “Aprovar e registrar tudo”; '
               'nada será registrado em duplicidade.')

LABELS = {'protocol': 'PROTOCOLO', 'requester': 'Solicitante', 'created': 'Data do Envio',
          'category': 'ENQUADRAMENTO', 'address': 'ENDEREÇO',
          'description': 'OCORRÊNCIA- Descrição sintética do pedido', 'neighborhood': 'BAIRRO'}


@st.cache_resource(show_spinner=False)
def components():
    # Um fluxo por processo: o lock contra clique duplo é compartilhado entre as sessões.
    return runtime.components()


def main():
    st.set_page_config(page_title='JANUS | Inteligência Gambá', page_icon='📄', layout='wide')
    st.caption('INTELIGÊNCIA GAMBÁ  /  AMBIENTE DE TESTE')
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
    if not runtime.allowed(getattr(st.user, 'email', None)):
        st.error('Acesso não autorizado. Entre com a conta indicada pela equipe técnica.')
        if runtime.mode() == 'google':
            st.button('Sair', on_click=st.logout)
        return
    try:
        flow = components()
    except Exception:
        st.error('O ambiente de teste está indisponível. Solicite à equipe técnica a revisão da configuração.')
        return
    drive = flow.drive
    if hasattr(drive, 'entrada'):
        st.link_button('Abrir pasta de entrada', 'https://drive.google.com/drive/folders/' + drive.entrada)
    else:
        st.info('Demonstração com PDFs inventados. Nenhum dado do gabinete é utilizado.')
    if st.button('Processar PDFs', type='primary'):
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
            if not hasattr(drive, 'entrada'):
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
        try:
            target = BytesIO()
            flow.export(target)
            st.session_state.export = target.getvalue()
        except Exception:
            st.error('Não foi possível preparar o Excel. Tente novamente.')
    if 'export' in st.session_state:
        st.download_button('Baixar Excel (.xlsx)', st.session_state.export,
            file_name='JANUS-teste.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    main()
