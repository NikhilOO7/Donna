'use client';

import React, { useState, useEffect } from 'react';
import {
  FileText,
  MessageSquare,
  Mic,
  BarChart3,
  Menu,
  X,
  Activity,
  Sparkles,
} from 'lucide-react';
import DocumentUpload from '@/components/documents/DocumentUpload';
import DocumentList from '@/components/documents/DocumentList';
import ChatInterface from '@/components/chat/ChatInterface';
import VoiceInterface from '@/components/voice/VoiceInterface';
import AnalyticsDashboard from '@/components/analytics/AnalyticsDashboard';
import ErrorBoundary from '@/components/ErrorBoundary';
import { apiClient } from '@/lib/api-client';
import type { HealthStatus, WebSocketMessage } from '@/types';

type Tab = 'documents' | 'chat' | 'voice' | 'analytics';

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>('documents');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null);
  const [documentRefreshTrigger, setDocumentRefreshTrigger] = useState(0);
  const [notifications, setNotifications] = useState<WebSocketMessage[]>([]);

  // Fetch health status on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const health = await apiClient.healthCheck();
        setHealthStatus(health);
      } catch (error) {
        console.error('Health check failed:', error);
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000); // Check every 30s

    return () => clearInterval(interval);
  }, []);

  // Setup WebSocket for real-time updates (with auto-reconnection)
  useEffect(() => {
    let wsHandle: { ws: WebSocket; close: () => void } | null = null;

    try {
      wsHandle = apiClient.createWebSocket(
        (message: WebSocketMessage) => {
          console.log('WebSocket message:', message);

          // Add notification
          setNotifications((prev) => [...prev, message].slice(-5)); // Keep last 5

          // Trigger document list refresh
          if (
            message.type === 'processing_completed' ||
            message.type === 'document_uploaded' ||
            message.type === 'document_deleted'
          ) {
            setDocumentRefreshTrigger((prev) => prev + 1);
          }

          // Show browser notification
          if (message.type === 'processing_completed' && 'Notification' in window) {
            if (Notification.permission === 'granted') {
              new Notification('Document Processed', {
                body: `${message.filename || 'Document'} has been processed successfully`,
                icon: '/favicon.ico',
              });
            }
          }
        },
        () => {
          // Reconnection handles recovery automatically
        }
      );
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
    }

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }

    return () => {
      wsHandle?.close();
    };
  }, []);

  const tabs = [
    { id: 'documents' as Tab, name: 'Documents', icon: FileText },
    { id: 'chat' as Tab, name: 'Chat', icon: MessageSquare },
    { id: 'voice' as Tab, name: 'Voice', icon: Mic },
    { id: 'analytics' as Tab, name: 'Analytics', icon: BarChart3 },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="lg:hidden p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                {sidebarOpen ? (
                  <X className="w-5 h-5 text-gray-600" />
                ) : (
                  <Menu className="w-5 h-5 text-gray-600" />
                )}
              </button>

              <div className="flex items-center gap-2">
                <Sparkles className="w-6 h-6 text-primary-600" />
                <h1 className="text-xl font-bold text-gray-900">
                  Voice Document Intelligence
                </h1>
              </div>
            </div>

            {/* Health Status */}
            {healthStatus && (
              <div className="flex items-center gap-2">
                <div className={`
                  w-2 h-2 rounded-full
                  ${healthStatus.status === 'healthy' ? 'bg-green-500' :
                    healthStatus.status === 'degraded' ? 'bg-yellow-500' :
                    'bg-red-500'}
                  animate-pulse
                `} />
                <span className="text-sm text-gray-600 hidden sm:inline">
                  {healthStatus.status}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex">
        {/* Sidebar - Tabs */}
        <aside
          className={`
            ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
            fixed lg:static inset-y-0 left-0 z-40 w-64
            bg-white border-r border-gray-200
            transition-transform duration-300 ease-in-out
            mt-16 lg:mt-0
          `}
        >
          <nav className="p-4 space-y-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;

              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    setActiveTab(tab.id);
                    setSidebarOpen(false);
                  }}
                  className={`
                    w-full flex items-center gap-3 px-4 py-3 rounded-lg
                    transition-all duration-200
                    ${isActive
                      ? 'bg-primary-50 text-primary-700 font-medium'
                      : 'text-gray-700 hover:bg-gray-50'
                    }
                  `}
                >
                  <Icon className="w-5 h-5" />
                  <span>{tab.name}</span>
                </button>
              );
            })}
          </nav>

          {/* Recent Notifications */}
          {notifications.length > 0 && (
            <div className="p-4 border-t border-gray-200 mt-auto">
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">
                Recent Updates
              </h3>
              <div className="space-y-2">
                {notifications.slice(-3).reverse().map((notif, idx) => (
                  <div
                    key={idx}
                    className="text-xs p-2 bg-gray-50 rounded text-gray-600"
                  >
                    <Activity className="w-3 h-3 inline mr-1" />
                    {notif.type.replace(/_/g, ' ')}
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>

        {/* Overlay for mobile */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/20 z-30 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main Content Area */}
        <main className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {/* Documents Tab */}
            {activeTab === 'documents' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">
                    Document Management
                  </h2>
                  <p className="text-gray-600">
                    Upload and manage your documents with intelligent processing
                  </p>
                </div>

                {/* Upload Section */}
                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">
                    Upload Document
                  </h3>
                  <DocumentUpload
                    onUploadSuccess={() => {
                      setDocumentRefreshTrigger((prev) => prev + 1);
                    }}
                  />
                </div>

                {/* Document List */}
                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">
                    Your Documents
                  </h3>
                  <DocumentList refreshTrigger={documentRefreshTrigger} />
                </div>
              </div>
            )}

            {/* Chat Tab */}
            {activeTab === 'chat' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">
                    Document Chat
                  </h2>
                  <p className="text-gray-600">
                    Ask questions about your documents using AI
                  </p>
                </div>

                <div className="h-[calc(100vh-12rem)]">
                  <ErrorBoundary sectionName="Chat">
                    <ChatInterface />
                  </ErrorBoundary>
                </div>
              </div>
            )}

            {/* Voice Tab */}
            {activeTab === 'voice' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">
                    Voice Assistant
                  </h2>
                  <p className="text-gray-600">
                    Talk to your documents using natural voice
                  </p>
                </div>

                <ErrorBoundary sectionName="Voice">
                  <VoiceInterface />
                </ErrorBoundary>
              </div>
            )}

            {/* Analytics Tab */}
            {activeTab === 'analytics' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-2">
                    Analytics & Performance
                  </h2>
                  <p className="text-gray-600">
                    Monitor usage and performance metrics
                  </p>
                </div>

                <ErrorBoundary sectionName="Analytics">
                  <AnalyticsDashboard />
                </ErrorBoundary>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
