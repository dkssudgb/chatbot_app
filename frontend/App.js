import React, { useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import Markdown from 'react-native-markdown-display';
// 스트리밍 응답(ReadableStream)을 웹과 iOS/Android 모두에서 읽을 수 있는 fetch
import { fetch } from 'expo/fetch';

// frontend/.env 의 EXPO_PUBLIC_API_URL 로 변경 가능 (Android 에뮬레이터: http://10.0.2.2:8000)
const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

// 백엔드에 보낼 최근 대화 개수 (길어질수록 LLM 토큰이 늘어남)
const MAX_HISTORY = 10;

const WELCOME = {
  id: 'welcome',
  role: 'bot',
  text: '안녕하세요! 동문회 회원 정보를 물어보세요.\n\n예: "울산에서 일하는 선생님 찾아줘", "30기 회원은 몇 명이야?"',
};

class ServerError extends Error {}

async function getServerError(res) {
  try {
    const data = await res.json();
    return new ServerError(`오류가 발생했습니다: ${data.detail ?? res.status}`);
  } catch {
    return new ServerError(`오류가 발생했습니다: ${res.status}`);
  }
}

function getErrorMessage(error) {
  if (error instanceof ServerError) return error.message;
  return `서버(${API_URL})에 연결할 수 없습니다. 백엔드가 실행 중인지 확인해 주세요.`;
}

export default function App() {
  const [messages, setMessages] = useState([WELCOME]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef(null);
  const inputRef = useRef(null);

  const addMessage = (role, text, isError = false) => {
    const id = `${Date.now()}-${role}`;
    setMessages(prev => [...prev, { id, role, text, isError }]);
    return id;
  };

  const updateMessage = (id, changes) => {
    setMessages(prev => prev.map(m => (m.id === id ? { ...m, ...changes } : m)));
  };

  const handleSend = async () => {
    const text = question.trim();
    if (!text || loading) return;
    // 전송 버튼을 눌러도 포커스가 입력창에 남도록
    inputRef.current?.focus();

    // 안내 문구와 오류 메시지는 대화 기록에서 제외
    const chatHistory = messages
      .filter(m => m.id !== WELCOME.id && !m.isError)
      .slice(-MAX_HISTORY)
      .map(m => `${m.role === 'user' ? '사용자' : '챗봇'}: ${m.text}`);

    addMessage('user', text);
    // 빈 답변 말풍선을 먼저 만들고, 받은 청크를 이어 붙인다.
    const botId = addMessage('bot', '');
    setQuestion('');
    setLoading(true);

    let answer = '';
    try {
      const res = await fetch(`${API_URL}/ask/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, chat_history: chatHistory }),
      });
      if (!res.ok) throw await getServerError(res);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        answer += decoder.decode(value, { stream: true });
        updateMessage(botId, { text: answer });
      }
      answer += decoder.decode();
      updateMessage(botId, { text: answer || '답변을 받지 못했습니다.' });
    } catch (error) {
      // 답변 도중 연결이 끊기면 받은 내용은 남기고 오류만 덧붙인다.
      const message = getErrorMessage(error);
      updateMessage(botId, { text: answer ? `${answer}\n\n(${message})` : message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  const renderItem = ({ item }) => {
    const isUser = item.role === 'user';
    // 첫 청크가 오기 전(SQL 생성·실행 중)에는 대기 표시
    if (!isUser && !item.text) {
      return (
        <View style={[styles.bubble, styles.botBubble, styles.loadingBubble]}>
          <ActivityIndicator size="small" color="#4a6cf7" />
          <Text style={styles.loadingText}>회원 정보를 찾는 중…</Text>
        </View>
      );
    }
    return (
      <View style={[styles.bubble, isUser ? styles.userBubble : styles.botBubble, item.isError && styles.errorBubble]}>
        {isUser ? (
          <Text style={styles.userText}>{item.text}</Text>
        ) : (
          <Markdown style={markdownStyles}>{item.text}</Markdown>
        )}
      </View>
    );
  };

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.inner}>
        <Text style={styles.title}>동문회 회원 챗봇</Text>

        <FlatList
          ref={listRef}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          data={messages}
          keyExtractor={item => item.id}
          renderItem={renderItem}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
        />

        <View style={styles.inputRow}>
          <TextInput
            ref={inputRef}
            autoFocus
            style={styles.input}
            placeholder="질문을 입력하세요"
            value={question}
            onChangeText={setQuestion}
            onSubmitEditing={handleSend}
            // Enter로 전송한 뒤에도 포커스 유지 (웹: blurOnSubmit, 앱: submitBehavior)
            // 답변을 기다리는 동안에도 다음 질문을 입력할 수 있다. 전송은 handleSend 에서 막는다.
            blurOnSubmit={false}
            submitBehavior="submit"
            returnKeyType="send"
          />
          <Pressable
            style={[styles.sendButton, (loading || !question.trim()) && styles.sendButtonDisabled]}
            onPress={handleSend}
            disabled={loading || !question.trim()}
          >
            <Text style={styles.sendButtonText}>전송</Text>
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f6f8',
  },
  inner: {
    flex: 1,
    width: '100%',
    maxWidth: 720,
    alignSelf: 'center',
    paddingTop: Platform.OS === 'web' ? 20 : 50,
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  title: {
    fontSize: 22,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingVertical: 8,
  },
  bubble: {
    maxWidth: '85%',
    borderRadius: 14,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginVertical: 4,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#4a6cf7',
  },
  botBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#e2e4e9',
  },
  errorBubble: {
    backgroundColor: '#fdecec',
    borderColor: '#f3b4b4',
  },
  userText: {
    color: '#fff',
    fontSize: 16,
  },
  loadingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
  },
  loadingText: {
    marginLeft: 8,
    color: '#666',
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
  },
  input: {
    flex: 1,
    height: 44,
    borderColor: '#ccc',
    borderWidth: 1,
    borderRadius: 22,
    paddingHorizontal: 16,
    backgroundColor: '#fff',
    fontSize: 16,
  },
  sendButton: {
    marginLeft: 8,
    height: 44,
    paddingHorizontal: 18,
    borderRadius: 22,
    justifyContent: 'center',
    backgroundColor: '#4a6cf7',
  },
  sendButtonDisabled: {
    backgroundColor: '#a9b7f5',
  },
  sendButtonText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
});

const markdownStyles = {
  body: { fontSize: 16, color: '#222' },
  paragraph: { marginTop: 2, marginBottom: 2 },
  link: { color: '#4a6cf7' },
  bullet_list: { marginVertical: 2 },
};
