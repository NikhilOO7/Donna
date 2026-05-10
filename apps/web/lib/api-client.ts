// API Client for Voice Document Intelligence System
import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  Document,
  QueryRequest,
  QueryResponse,
  HealthStatus,
  UsageAnalytics,
  PerformanceAnalytics,
  VoiceToken,
} from '@/types';

class ApiClient {
  private client: AxiosInstance;
  private wsUrl: string;

  constructor() {
    const baseURL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    this.wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    });

    // Request interceptor
    this.client.interceptors.request.use(
      (config) => {
        console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
        return config;
      },
      (error) => {
        return Promise.reject(error);
      }
    );

    // Response interceptor
    this.client.interceptors.response.use(
      (response) => {
        console.log(`[API] Response:`, response.status);
        return response;
      },
      (error: AxiosError) => {
        console.error(`[API] Error:`, error.response?.status, error.message);
        return Promise.reject(error);
      }
    );
  }

  // Health Check
  async healthCheck(): Promise<HealthStatus> {
    const response = await this.client.get<HealthStatus>('/health');
    return response.data;
  }

  // Document Management
  async uploadDocument(file: File, useEnhanced: boolean = true): Promise<{ document_id: string; filename: string; status: string; message: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.client.post(
      `/api/v1/documents/upload?use_enhanced=${useEnhanced}`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );

    return response.data;
  }

  async listDocuments(skip: number = 0, limit: number = 10, status?: string): Promise<{
    documents: Document[];
    total: number;
    skip: number;
    limit: number;
  }> {
    const params: any = { skip, limit };
    if (status) params.status = status;

    const response = await this.client.get('/api/v1/documents', { params });
    return response.data;
  }

  async getDocument(documentId: string): Promise<Document> {
    const response = await this.client.get<Document>(`/api/v1/documents/${documentId}`);
    return response.data;
  }

  async deleteDocument(documentId: string): Promise<{ message: string }> {
    const response = await this.client.delete(`/api/v1/documents/${documentId}`);
    return response.data;
  }

  // Query
  async queryDocuments(request: QueryRequest, signal?: AbortSignal): Promise<QueryResponse> {
    const response = await this.client.post<QueryResponse>('/api/v1/query', request, { signal });
    return response.data;
  }

  // Voice
  async getVoiceToken(roomName: string = 'document-chat', participantName: string = 'user'): Promise<VoiceToken> {
    const response = await this.client.get<VoiceToken>('/api/v1/voice/token', {
      params: { room_name: roomName, participant_name: participantName },
    });
    return response.data;
  }

  // Analytics
  async getUsageAnalytics(): Promise<UsageAnalytics> {
    const response = await this.client.get<UsageAnalytics>('/api/v1/analytics/usage');
    return response.data;
  }

  async getPerformanceAnalytics(): Promise<PerformanceAnalytics> {
    const response = await this.client.get<PerformanceAnalytics>('/api/v1/analytics/performance');
    return response.data;
  }

  // Test
  async testDemo(): Promise<any> {
    const response = await this.client.get('/api/v1/test/demo');
    return response.data;
  }

  async processSampleDocument(): Promise<{ document_id: string; message: string }> {
    const response = await this.client.post('/api/v1/test/process-sample');
    return response.data;
  }

  // WebSocket with automatic reconnection
  createWebSocket(
    onMessage: (message: any) => void,
    onError?: (error: Event) => void,
    options?: { maxReconnectAttempts?: number }
  ): { ws: WebSocket; close: () => void } {
    const maxAttempts = options?.maxReconnectAttempts ?? 10;
    let reconnectAttempts = 0;
    let pingInterval: ReturnType<typeof setInterval> | null = null;
    let intentionalClose = false;
    let currentWs: WebSocket;

    const connect = (): WebSocket => {
      const ws = new WebSocket(`${this.wsUrl}/ws`);

      ws.onopen = () => {
        console.log('[WebSocket] Connected');
        reconnectAttempts = 0;

        // Keep-alive ping
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          if (event.data === 'pong') return;
          const message = JSON.parse(event.data);
          onMessage(message);
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error);
        }
      };

      ws.onerror = () => {
        // Suppressed — reconnection handles recovery automatically
        if (onError) onError(new Event('error'));
      };

      ws.onclose = () => {
        if (pingInterval) clearInterval(pingInterval);
        pingInterval = null;

        if (intentionalClose) {
          console.log('[WebSocket] Closed intentionally');
          return;
        }

        if (reconnectAttempts < maxAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
          reconnectAttempts++;
          console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${maxAttempts})`);
          setTimeout(() => {
            currentWs = connect();
          }, delay);
        } else {
          console.error('[WebSocket] Max reconnect attempts reached');
        }
      };

      currentWs = ws;
      return ws;
    };

    currentWs = connect();

    return {
      get ws() { return currentWs; },
      close: () => {
        intentionalClose = true;
        if (pingInterval) clearInterval(pingInterval);
        currentWs.close();
      },
    };
  }
}

// Export singleton instance
export const apiClient = new ApiClient();
