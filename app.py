import streamlit as st
import sqlite3
import json
from groq import Groq
from duckduckgo_search import DDGS

st.set_page_config(page_title="Agente Coder com Memória", page_icon="🤖")
st.title("🤖 Agente Coder - Memória Permanente & Chat")

# --- BANCO DE DADOS (SQLite) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    # Tabela de histórico de conversas
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT)''')
    # Tabela de fatos e memória sobre o usuário
    c.execute('''CREATE TABLE IF NOT EXISTS perfil 
                 (chave TEXT PRIMARY KEY, valor TEXT)''')
    conn.commit()
    conn.close()

def salvar_mensagem(role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    conn.close()

def carregar_historico():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico")
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def salvar_perfil(chave, valor):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO perfil (chave, valor) VALUES (?, ?)", (chave, valor))
    conn.commit()
    conn.close()

def carregar_perfil():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chave, valor FROM perfil")
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def limpar_memoria():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM historico")
    c.execute("DELETE FROM perfil")
    conn.commit()
    conn.close()

init_db()

# --- AUTENTICAÇÃO GROQ ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("Chave GROQ_API_KEY não encontrada nos Secrets do Streamlit.")
    st.stop()

# --- BARRA LATERAL (MEMÓRIA & CONTROLES) ---
st.sidebar.title("🧠 Memória do Agente")
perfil_atual = carregar_perfil()
if perfil_atual:
    st.sidebar.subheader("O que eu sei sobre você:")
    for k, v in perfil_atual.items():
        st.sidebar.write(f"- **{k}:** {v}")
else:
    st.sidebar.info("Ainda não aprendi fatos fixos sobre você.")

if st.sidebar.button("🗑️ Apagar Toda Memória"):
    limpar_memoria()
    st.session_state.messages = []
    st.rerun()

# --- CARREGAMENTO DE MENSAGENS ---
if "messages" not in st.session_state:
    st.session_state.messages = carregar_historico()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- PROCESSAMENTO DO CHAT ---
if user_input := st.chat_input("Digite sua dúvida ou ensine algo ao agente..."):
    # Salva entrada no banco e na sessão
    salvar_mensagem("user", user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Busca Web Automática
    extra_context = ""
    try:
        with DDGS() as ddgs:
            results = [f"- {r['title']}: {r['body']}" for r in ddgs.text(user_input, max_results=3)]
            if results:
                extra_context = "\n\n--- Resultados da Busca na Web em Tempo Real ---\n" + "\n".join(results)
    except Exception as e:
        extra_context = f"\n[Busca web desativada: {e}]"

    # Monta o contexto de perfil retido
    fatos_perfil = carregar_perfil()
    texto_perfil = "\n".join([f"{k}: {v}" for k, v in fatos_perfil.items()]) if fatos_perfil else "Nenhum dado salvo."

    system_prompt = f"""Você é um assistente especialista em programação com memória de longo prazo.
Memória retida sobre o usuário:
{texto_perfil}

Regra Importante: Responda a dúvida do usuário considerando a memória retida. 
Se o usuário lhe disser o nome dele, preferências ou detalhes sobre o projeto, guarde essa informação naturalmente na conversa."""

    messages_payload = [{"role": "system", "content": system_prompt}]
    
    # Envia o histórico recente de conversas para a API
    for m in st.session_state.messages[-10:]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    
    # Adiciona a busca web na última mensagem do usuário
    messages_payload[-1]["content"] += extra_context

    with st.chat_message("assistant"):
        try:
            clean_api_key = str(api_key).strip()
            client = Groq(api_key=clean_api_key)
            
            response = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages_payload
            )
            bot_reply = response.choices[0].message.content
            st.markdown(bot_reply)
            
            # Salva no banco e na sessão
            salvar_mensagem("assistant", bot_reply)
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})

            # Extração de memória (nome, preferências) em segundo plano
            if "meu nome é" in user_input.lower() or "me chamo" in user_input.lower():
                partes = user_input.split()
                nome = partes[-1].capitalize()
                salvar_perfil("Nome", nome)
                st.rerun()

        except Exception as err:
            st.error(f"Erro na API da Groq: {err}")
