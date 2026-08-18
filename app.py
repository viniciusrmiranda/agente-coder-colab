import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- BANCO DE DADOS (SQLite Avançado com Sessões) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    # Tabela de sessões de conversa
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # Tabela de histórico ligada ao chat_id
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    # Tabela de perfil
    c.execute('''CREATE TABLE IF NOT EXISTS perfil 
                 (user_email TEXT, chave TEXT, valor TEXT, PRIMARY KEY (user_email, chave))''')
    
    # Migrações caso colunas não existam
    try:
        c.execute("ALTER TABLE historico ADD COLUMN chat_id TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def listar_conversas(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chat_id, titulo FROM conversas WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    return rows

def criar_nova_conversa(email, titulo="Nova Conversa"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO conversas (chat_id, user_email, titulo) VALUES (?, ?, ?)", (chat_id, email, titulo))
    conn.commit()
    conn.close()
    return chat_id

def atualizar_titulo_conversa(chat_id, texto):
    titulo = texto[:30] + "..." if len(texto) > 30 else texto
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("UPDATE conversas SET titulo = ? WHERE chat_id = ? AND titulo = 'Nova Conversa'", (titulo, chat_id))
    conn.commit()
    conn.close()

def salvar_mensagem(chat_id, email, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (chat_id, user_email, role, content) VALUES (?, ?, ?, ?)", (chat_id, email, role, content))
    conn.commit()
    conn.close()

def carregar_historico_chat(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def deletar_conversa(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM conversas WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM historico WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def carregar_perfil(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    try:
        c.execute("SELECT chave, valor FROM perfil WHERE user_email = ?", (email,))
        rows = c.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        conn.close()
        return {}

init_db()

# --- VALIDAR GROQ API KEY E MODELO ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets.")
    st.stop()

@st.cache_data(ttl=3600)
def obter_modelo_ativo(key):
    try:
        client = Groq(api_key=key.strip())
        models_page = client.models.list()
        model_ids = [m.id for m in models_page.data]
        
        preferenciais = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it"
        ]
        
        for p in preferenciais:
            if p in model_ids:
                return p
        return model_ids[0] if model_ids else "llama-3.1-8b-instant"
    except Exception:
        return "llama-3.1-8b-instant"

active_model = obter_modelo_ativo(str(api_key))

# --- GERENCIAMENTO DE SESSÃO DO CHAT ---
conversas_usuario = listar_conversas(user_email)

if "active_chat_id" not in st.session_state or not st.session_state.active_chat_id:
    if conversas_usuario:
        st.session_state.active_chat_id = conversas_usuario[0][0]
    else:
        st.session_state.active_chat_id = criar_nova_conversa(user_email)

# --- BARRA LATERAL (HISTÓRICO ESTILO CHATGPT) ---
st.sidebar.title("💬 Conversas")

if st.sidebar.button("➕ Nova Conversa", use_container_width=True):
    novo_id = criar_nova_conversa(user_email)
    st.session_state.active_chat_id = novo_id
    st.rerun()

st.sidebar.markdown("---")

# Lista histórico de conversas
for cid, titulo in conversas_usuario:
    col1, col2 = st.sidebar.columns([0.8, 0.2])
    label = f"📌 {titulo}" if cid == st.session_state.active_chat_id else titulo
    if col1.button(label, key=f"chat_{cid}", use_container_width=True):
        st.session_state.active_chat_id = cid
        st.rerun()
    if col2.button("🗑️", key=f"del_{cid}"):
        deletar_conversa(cid)
        st.session_state.active_chat_id = None
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.write(f"Conectado como:\n**{user_email}**")
st.sidebar.caption(f"🤖 Modelo Groq: {active_model}")

if st.sidebar.button("🚪 Sair / Logout"):
    st.logout()

# --- ÁREA PRINCIPAL DO CHAT ---
st.title("🤖 Agente Coder")

# Carrega histórico da conversa ativa
messages = carregar_historico_chat(st.session_state.active_chat_id)

for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- CAMPO DE ARQUIVO E ENTRADA DENTRO DA INTERFACE PRINCIPAL ---
MAX_CHARACTERS = 12000

# Expander para anexar arquivo direto na conversa
with st.expander("📎 Anexar arquivo a esta mensagem", expanded=False):
    uploaded_file = st.file_uploader(
        "Selecione um arquivo (PDF, TXT, PY, JSON, MD, CSV)", 
        type=["pdf", "txt", "py", "json", "md", "csv"],
        key=f"file_{st.session_state.active_chat_id}"
    )

if user_input := st.chat_input("Digite sua mensagem..."):
    # Atualiza o título da conversa se for a primeira mensagem
    if len(messages) == 0:
        atualizar_titulo_conversa(st.session_state.active_chat_id, user_input)

    file_content_context = ""
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".pdf"):
                pdf_reader = pypdf.PdfReader(uploaded_file)
                pdf_text = "\n".join([page.extract_text() or "" for page in pdf_reader.pages])
                if len(pdf_text) > MAX_CHARACTERS:
                    pdf_text = pdf_text[:MAX_CHARACTERS] + "\n\n[...Texto resumido...]"
                file_content_context = f"\n\n--- Anexo: {uploaded_file.name} ---\n{pdf_text}\n--- Fim do Anexo ---"
            else:
                file_text = uploaded_file.read().decode("utf-8")
                if len(file_text) > MAX_CHARACTERS:
                    file_text = file_text[:MAX_CHARACTERS] + "\n\n[...Texto resumido...]"
                file_content_context = f"\n\n--- Anexo: {uploaded_file.name} ---\n{file_text}\n--- Fim do Anexo ---"
        except Exception as e:
            st.error(f"Erro ao ler arquivo: {e}")

    # Exibe a mensagem do usuário com indicação visual do anexo
    user_display = user_input
    if uploaded_file is not None:
        user_display = f"📄 *Anexo: {uploaded_file.name}*\n\n" + user_input

    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", user_display)
    with st.chat_message("user"):
        st.markdown(user_display)

    # Busca Web
    extra_context = ""
    try:
        with DDGS() as ddgs:
            results = [f"- {r['title']}: {r['body']}" for r in ddgs.text(user_input, max_results=3)]
            if results:
                extra_context = "\n\n--- Resultados de Pesquisa ---\n" + "\n".join(results)
    except Exception as e:
        extra_context = f"\n[Busca indisponível: {e}]"

    fatos_perfil = carregar_perfil(user_email)
    texto_perfil = "\n".join([f"{k}: {v}" for k, v in fatos_perfil.items()]) if fatos_perfil else "Sem preferências registradas."

    system_prompt = f"""Você é um assistente especialista em código.
Usuário logado via Google: {user_email}
Perfil retido do usuário:
{texto_perfil}"""

    # Carrega histórico atualizado do banco
    history_messages = carregar_historico_chat(st.session_state.active_chat_id)
    messages_payload = [{"role": "system", "content": system_prompt}]
    
    for m in history_messages[-6:]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    
    # Injeta o conteúdo real do arquivo no prompt enviado ao LLM
    if file_content_context:
        messages_payload[-1]["content"] += file_content_context
    if extra_context:
        messages_payload[-1]["content"] += extra_context

    with st.chat_message("assistant"):
        try:
            client = Groq(api_key=str(api_key).strip())
            response = client.chat.completions.create(
                model=active_model,
                messages=messages_payload
            )
            bot_reply = response.choices[0].message.content
            st.markdown(bot_reply)
            salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
        except Exception as err:
            st.error(f"Erro ao processar mensagem na Groq: {err}")

    st.rerun()
