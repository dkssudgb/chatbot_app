import React, { useState } from 'react';
import { StyleSheet, TextInput, Button, View, Text, ScrollView } from 'react-native';
import axios from 'axios';

export default function App() {
  const [question, setQuestion] = useState('');
  const [response, setResponse] = useState('');

  const handleChat = async () => {
    try {
      const res = await axios.post('http://127.0.0.1:8000/chat', { question });
      setResponse(res.data.answer);
    } catch (error) {
      setResponse('Error: Unable to fetch response.');
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Chat with Gemini</Text>
      <TextInput
        style={styles.input}
        placeholder="Ask me anything..."
        value={question}
        onChangeText={setQuestion}
      />
      <Button title="Send" onPress={handleChat} />
      <ScrollView style={styles.responseContainer}>
        <Text style={styles.response}>{response}</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 20,
  },
  input: {
    height: 40,
    borderColor: 'gray',
    borderWidth: 1,
    marginBottom: 10,
    paddingHorizontal: 8,
  },
  responseContainer: {
    marginTop: 20,
    padding: 10,
    backgroundColor: '#f0f0f0',
  },
  response: {
    fontSize: 16,
    color: 'black',
  },
});
