"""Apenas dados inventados; nenhum conteúdo das referências reais."""
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

PROTOCOL = 'C123456789012345678'


def text(protocol=PROTOCOL, events=False):
    common = f'''Serviço: Sistema Janus / {'Eventos' if events else 'Zeladoria'}
Protocolo:{protocol}
Interessado (a): Pessoa Sintetica Interessada
Responsável pelo
preenchimento:
Pessoa Sintetica Responsavel
'''
    if events:
        return common + '''Tipo de pedido: Organizacao
Descrição do Evento
Nome do Evento Evento sintetico
Endereço do evento Rua Exemplo 100 de 100 ao fim - lado par, Bairro Exemplo,
Santo André - SP , 00000-000
Horário de início 10:00
Enquadramento
Enquadramento cultural
Quando assinalado outro,
descrever abaixo:
-
Descrição objetiva do
pedido
Pedido sintetico para teste.
Informações
complementares
Texto que nao integra o pedido.
'''
    return common + f'''E-mail do responsavel:
nao-usar@example.invalid
Enquadramento: Manutencao sintetica
Local: -
Endereço: Rua Exemplo 100, Bairro Exemplo, Santo André - SP ,
00000-000
Descrição sintética do
pedido:
Pedido sintetico para teste.
Solicitação
1
Protocolo: {protocol}
'''


def pdf(path, content, pages=2, date='D:20261028010000Z'):
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica'),
                                 NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject(
            {NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        lines = content.splitlines() if index == 0 else ['Anexo sintetico']
        commands = [b'BT /F1 10 Tf 12 TL 30 760 Td']
        for line in lines:
            escaped = line.encode('cp1252').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
            commands.append(b'(' + escaped + b') Tj T*')
        commands.append(b'ET')
        stream.set_data(b'\n'.join(commands))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if date:
        writer.add_metadata({'/CreationDate': date})
    writer.write(path)
