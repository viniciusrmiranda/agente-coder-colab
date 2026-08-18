import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS

st.set_page_config(page_title="Agente Coder", page_icon="🤖")

# --- LOGIN POR E-MAIL ---
if "logged_user" not in st.session_state:
    st.session_state.logged_user = None

if not st.session_state.logged_user:
    st.title("🤖 Agente Coder - Entrar")
    st.write("Digite seu e-mail para acessar seu histórico e perfil de memória.")
    
    email_input = st.text_input("Seu e-mail (ex: usuario@gmail.com):")
    if st.button("🔑 Entrar"):
        if email_input and "@" in email_input:
            st.session_state.logged_user = email_input.strip().lower()
            st.rerun()
        else:
            st.warning("Insira um e-mail válido.")
    st.stop()

user_email = st.session_state.logged_user
st.title(f"🤖 Olá, {user_email}!")

# --- BANCO DE DADOS (SQLite) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, role TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS perfil 
                 (user_email TEXT, chave TEXT, valor TEXT, PRIMARY KEY (user_email, chave))''')
    conn.commit()
    conn.close()

def salvar_mensagem(email, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (user_email, role, content) VALUES (?, ?, ?)", (email, role, content))
    conn.commit()
    conn.close()

def carregar_historico(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE user_email = ?", (email,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def carregar_perfil(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chave, valor FROM perfil WHERE user_email = ?", (email,))
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def limpar_memoria_usuario(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM historico WHERE user_email = ?", (email,))
    c.execute("DELETE FROM perfil WHERE user_email = ?", (email,))
    conn.commit()
    conn.close()

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets do Streamlit.")
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.title("👤 Conta")
st.sidebar.write(f"Usuário: **{user_email}**")

if st.sidebar.button("🚪 Sair"):
    st.session_state.logged_user = None
    st.session_state.messages = []
    st.rerun()

perfil_atual = carregar_perfil(user_email)
if perfil_atual:
    st.sidebar.subheader("Memória Salva:")
    for k, v in perfil_atual.items():
        st.sidebar.write(f"- **{k}:** {v}")

if st.sidebar.button("🗑️ Limpar Minha Memória"):
    limpar_memoria_usuario(user_email)
    st.session_state.messages = []
    st.rerun()

# --- CHAT ---
if "messages" not in st.session_state:
    st.session_state.messages = carregar_historico(user_email)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Digite sua dúvida de programação..."):
    salvar_mensagem(user_email, "user", user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Busca na Web
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
Usuário atual: {user_email}
Perfil retido do usuário:
{texto_perfil}"""

    messages_payload = [{"role": "system", "content": system_prompt}]
    for m in st.session_state.messages[-10:]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    
    messages_payload[-1]["content"] += extra_context

    with st.chat_message("assistant"):
        try:
            client = Groq(api_key=str(api_key).strip())
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages_payload
            )
            bot_reply = response.choices[0].message.content
            st.markdown(bot_reply)
            
            salvar_mensagem(user_email, "assistant", bot_reply)
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})

        except Exception as err:
            st.error(f"Erro ao processar mensagem na Groq: {err}")
