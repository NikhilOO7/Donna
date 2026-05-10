'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, FileText, Sparkles } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { ChatMessage, QueryResponse } from '@/types';
import { generateRandomId, formatLatency } from '@/lib/utils';

export default function ChatInterface() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string>('');
  const [contextLevel, setContextLevel] = useState<'local' | 'document' | 'global'>('local');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setConversationId(`conv_${Date.now()}`);
    return () => {
      // Cancel any in-flight request on unmount
      abortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!inputValue.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: generateRandomId(),
      role: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    try {
      // Cancel any previous in-flight request
      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const startTime = Date.now();

      const response: QueryResponse = await apiClient.queryDocuments({
        query: inputValue,
        conversation_id: conversationId,
        context_level: contextLevel,
        use_enhanced: true,
      }, controller.signal);

      const latency = Date.now() - startTime;

      const assistantMessage: ChatMessage = {
        id: generateRandomId(),
        role: 'assistant',
        content: response.answer,
        timestamp: new Date().toISOString(),
        sources: response.sources,
        latency,
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error: any) {
      const errorMessage: ChatMessage = {
        id: generateRandomId(),
        role: 'assistant',
        content: `I apologize, but I encountered an error: ${error.response?.data?.error || error.message}`,
        timestamp: new Date().toISOString(),
      };

      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm border border-gray-200">
      {/* Header */}
      <div className="border-b border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Document Chat</h2>
            <p className="text-sm text-gray-500">Ask questions about your documents</p>
          </div>

          {/* Context Level Selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Context:</label>
            <select
              value={contextLevel}
              onChange={(e) => setContextLevel(e.target.value as any)}
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="local">Local</option>
              <option value="document">Document</option>
              <option value="global">Global</option>
            </select>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Sparkles className="w-12 h-12 text-primary-400 mb-3" />
            <h3 className="text-lg font-medium text-gray-900 mb-1">
              Start a conversation
            </h3>
            <p className="text-gray-500 text-sm max-w-md">
              Ask questions about your uploaded documents. The system uses contextual
              embeddings to provide accurate answers.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`
                max-w-[80%] rounded-lg px-4 py-3
                ${message.role === 'user'
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-900'
                }
              `}
            >
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>

              {/* Sources */}
              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
                  <p className="text-xs font-medium text-gray-600 uppercase">Sources:</p>
                  {message.sources.slice(0, 3).map((source, idx) => (
                    <div
                      key={idx}
                      className="bg-white rounded p-2 text-xs"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <FileText className="w-3 h-3 text-gray-500" />
                        <span className="font-medium text-gray-700">
                          Chunk {source.chunk_id.split('_').pop()}
                        </span>
                        <span className="text-gray-500">
                          • Score: {(source.score * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-gray-600 line-clamp-2">
                        {source.content}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {/* Latency */}
              {message.latency && (
                <div className="mt-2 text-xs opacity-70">
                  Response time: {formatLatency(message.latency)}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-4 py-3">
              <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t border-gray-200 p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Ask a question about your documents..."
            disabled={isLoading}
            className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || isLoading}
            className="px-6 py-2.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
