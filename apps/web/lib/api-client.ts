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

const TOKEN_KEY = 'donna_token';
const USER_KEY = 'donna_user';

export type AuthUser = {
  id: string;
  email: string;
  full_name?: string;
};

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

    // Verbose per-request logging only when explicitly opted in — otherwise
    // polling (meetings, health) floods the console. Set NEXT_PUBLIC_API_DEBUG=true.
    const apiDebug = process.env.NEXT_PUBLIC_API_DEBUG === 'true';

    // Request interceptor — attach JWT when present
    this.client.interceptors.request.use(
      (config) => {
        const token = this.getToken();
        if (token) {
          config.headers = config.headers || {};
          (config.headers as any).Authorization = `Bearer ${token}`;
        }
        if (apiDebug) console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
        return config;
      },
      (error) => {
        return Promise.reject(error);
      }
    );

    // Response interceptor
    this.client.interceptors.response.use(
      (response) => {
        if (apiDebug) console.log(`[API] Response:`, response.status);
        return response;
      },
      (error: AxiosError) => {
        // Expired/invalid session — clear it and send the user to login.
        if (error.response?.status === 401 && this.getToken()) {
          this.clearSession();
          if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
            window.location.href = '/login';
          }
        }
        // Errors always surface — they matter regardless of debug flag.
        console.error(`[API] Error:`, error.response?.status, error.message);
        return Promise.reject(error);
      }
    );
  }

  // --- Auth / session -----------------------------------------------------

  getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
  }

  isAuthenticated(): boolean {
    return Boolean(this.getToken());
  }

  getStoredUser(): AuthUser | null {
    if (typeof window === 'undefined') return null;
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? (JSON.parse(raw) as AuthUser) : null;
    } catch {
      return null;
    }
  }

  private storeSession(accessToken: string, user: AuthUser) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  clearSession() {
    if (typeof window === 'undefined') return;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  async register(email: string, password: string, fullName?: string): Promise<AuthUser> {
    const response = await this.client.post('/api/v1/auth/register', {
      email,
      password,
      full_name: fullName || '',
    });
    const { access_token, user } = response.data;
    this.storeSession(access_token, user);
    return user;
  }

  async login(email: string, password: string): Promise<AuthUser> {
    const response = await this.client.post('/api/v1/auth/login', { email, password });
    const { access_token, user } = response.data;
    this.storeSession(access_token, user);
    return user;
  }

  async me(): Promise<AuthUser> {
    const response = await this.client.get('/api/v1/auth/me');
    return response.data;
  }

  logout() {
    this.clearSession();
  }

  // Health Check
  async healthCheck(): Promise<HealthStatus> {
    const response = await this.client.get<HealthStatus>('/health');
    return response.data;
  }

  // Document Management
  async uploadDocument(file: File, useEnhanced: boolean = true, meetingId?: string): Promise<{ document_id: string; filename: string; status: string; message: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const meetingParam = meetingId ? `&meeting_id=${meetingId}` : '';
    const response = await this.client.post(
      `/api/v1/documents/upload?use_enhanced=${useEnhanced}${meetingParam}`,
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

  // Meetings
  async createMeeting(data: { title: string; description?: string; attendees?: any[]; scheduled_at?: string; meeting_type?: string; agenda?: string[] }): Promise<any> {
    const response = await this.client.post('/api/v1/meetings/', data);
    return response.data;
  }

  async listMeetings(skip: number = 0, limit: number = 50, status?: string): Promise<any> {
    const params: any = { skip, limit };
    if (status) params.status = status;
    const response = await this.client.get('/api/v1/meetings/', { params });
    return response.data;
  }

  async getMeeting(meetingId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}`);
    return response.data;
  }

  async deleteMeeting(meetingId: string): Promise<any> {
    const response = await this.client.delete(`/api/v1/meetings/${meetingId}`);
    return response.data;
  }

  async triggerResearch(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/research`);
    return response.data;
  }

  async getResearch(meetingId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/research`);
    return response.data;
  }

  async addDecision(meetingId: string, data: { decision_text: string; owner?: string; deadline?: string; context?: string; source_nudge_id?: string }): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/decisions`, data);
    return response.data;
  }

  async addActionItem(meetingId: string, data: { description: string; assignee?: string; deadline?: string; priority?: string }): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/action-items`, data);
    return response.data;
  }

  // Meeting lifecycle
  async startMeeting(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/start`);
    return response.data;
  }

  async endMeeting(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/end`);
    return response.data;
  }

  async getMeetingVoiceToken(meetingId: string, participantName: string, conference = false): Promise<any> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/voice-token`, {
      params: { participant_name: participantName, conference },
    });
    return response.data;
  }

  // Upload Transcript setup mode
  async importTranscript(data: {
    transcript_text: string; title?: string; meeting_type?: string;
  }): Promise<{ id: string; title: string; utterance_count: number }> {
    const response = await this.client.post('/api/v1/meetings/import-transcript', data);
    return response.data;
  }

  // Structured meeting prep (Smart Fill / conversational setup)
  async prepMeeting(input: string, current?: Record<string, any>): Promise<{
    role: string;
    meeting_type: string;
    meeting_goal: string;
    agenda_items: string[];
    risks_or_tensions: string[];
    confidence_notes: string;
  }> {
    const response = await this.client.post('/api/v1/meetings/prep', {
      input,
      ...(current ? { current } : {}),
    });
    return response.data;
  }

  async updateMeetingAttendees(
    meetingId: string,
    attendees: Array<{ name?: string; email?: string; voice_registered?: boolean }>,
  ): Promise<any> {
    const response = await this.client.patch(`/api/v1/meetings/${meetingId}`, { attendees });
    return response.data;
  }

  // Mid-meeting RAG query ("Ask Donna")
  async queryMeeting(meetingId: string, query: string, record = true): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/query`, {
      query,
      record,
    });
    return response.data;
  }

  // ---- Customer database connections (Settings) ----------------------
  // The password is write-only across this whole surface: it is sent on
  // create/update and never returned by any response.

  async listDataConnections(): Promise<{
    connections: any[]; encryption_ready: boolean; allow_private_hosts: boolean;
  }> {
    const response = await this.client.get('/api/v1/data-connections');
    return response.data;
  }

  async createDataConnection(body: {
    name: string; host: string; port: number; database: string;
    username: string; password: string; ssl_mode?: string; engine?: string;
  }): Promise<any> {
    const response = await this.client.post('/api/v1/data-connections', body);
    return response.data;
  }

  /** Connect, prove the account cannot write, and discover the schema. */
  async verifyDataConnection(id: string): Promise<{
    connection: any; check: any; tables: any[];
  }> {
    const response = await this.client.post(`/api/v1/data-connections/${id}/verify`);
    return response.data;
  }

  async updateDataConnection(id: string, body: Record<string, any>): Promise<any> {
    const response = await this.client.patch(`/api/v1/data-connections/${id}`, body);
    return response.data;
  }

  /** Snapshot approved tables so in-meeting insights need no live query. */
  async syncDataConnection(id: string): Promise<any> {
    const response = await this.client.post(`/api/v1/data-connections/${id}/sync`);
    return response.data;
  }

  async getDataConnectionAudit(id: string): Promise<{ queries: any[] }> {
    const response = await this.client.get(`/api/v1/data-connections/${id}/audit`);
    return response.data;
  }

  async deleteDataConnection(id: string): Promise<void> {
    await this.client.delete(`/api/v1/data-connections/${id}`);
  }

  async getMeetingCost(meetingId: string): Promise<{
    calls: number; total_tokens: number; estimated_usd: number; by_agent: Record<string, number>;
  }> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/cost`);
    return response.data;
  }

  async updateCanvas(meetingId: string, positions: Record<string, { x: number; y: number }>): Promise<any> {
    const response = await this.client.patch(`/api/v1/meetings/${meetingId}/canvas`, { positions });
    return response.data;
  }

  async toggleVoiceNudges(meetingId: string, enabled: boolean): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/voice-nudges`, { enabled });
    return response.data;
  }

  // Nudge feedback
  /** One insight in full, plus the other nudges from the same thread. */
  async getNudgeThread(meetingId: string, nudgeId: string): Promise<any> {
    const response = await this.client.get(
      `/api/v1/meetings/${meetingId}/nudges/${nudgeId}/thread`,
    );
    return response.data;
  }

  async dismissNudge(meetingId: string, nudgeId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/nudges/${nudgeId}/dismiss`);
    return response.data;
  }

  async pinNudge(meetingId: string, nudgeId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/nudges/${nudgeId}/pin`);
    return response.data;
  }

  // Transcript / Utterances
  async addUtterance(meetingId: string, speaker: string, text: string): Promise<any> {
    const response = await this.client.post(
      `/api/v1/meetings/${meetingId}/utterances`,
      { speaker, text },
    );
    return response.data;
  }

  async getTranscript(meetingId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/transcript`);
    return response.data;
  }

  // Summary
  async generateSummary(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/summarize`);
    return response.data;
  }

  async getSummary(meetingId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/summary`);
    return response.data;
  }

  async sendSummaryEmail(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/send-summary`);
    return response.data;
  }

  async updateDecisionStatus(meetingId: string, decisionId: string, status: string): Promise<any> {
    const response = await this.client.patch(`/api/v1/meetings/${meetingId}/decisions/${decisionId}`, { status });
    return response.data;
  }

  async updateActionItemStatus(meetingId: string, itemId: string, status: string): Promise<any> {
    const response = await this.client.patch(`/api/v1/meetings/${meetingId}/action-items/${itemId}`, { status });
    return response.data;
  }

  async listOpenItems(): Promise<any> {
    const response = await this.client.get('/api/v1/meetings/open-items');
    return response.data;
  }

  async sendInvites(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/invite`);
    return response.data;
  }

  async sendPreread(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/send-preread`);
    return response.data;
  }

  async sendFollowups(meetingId: string): Promise<any> {
    const response = await this.client.post(`/api/v1/meetings/${meetingId}/send-followups`);
    return response.data;
  }

  async googleCalendarStatus(): Promise<any> {
    const response = await this.client.get('/api/v1/integrations/google/status');
    return response.data;
  }

  async googleCalendarAuthUrl(): Promise<any> {
    const response = await this.client.get('/api/v1/integrations/google/auth-url');
    return response.data;
  }

  async googleCalendarSync(): Promise<any> {
    const response = await this.client.post('/api/v1/integrations/google/sync');
    return response.data;
  }

  async downloadCalendar(meetingId: string): Promise<void> {
    const response = await this.client.get(`/api/v1/meetings/${meetingId}/calendar.ics`, { responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data], { type: 'text/calendar' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'donna-meeting.ics';
    a.click();
    URL.revokeObjectURL(url);
  }

  async getDocumentElements(documentId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/documents/${documentId}/elements`);
    return response.data;
  }

  async getDocumentKnowledgeGraph(documentId: string): Promise<any> {
    const response = await this.client.get(`/api/v1/documents/${documentId}/knowledge-graph`);
    return response.data;
  }

  /**
   * Open a meeting-scoped WebSocket. Returns a cleanup function.
   * Pushed event types: "nudge_created", "utterance_added".
   */
  connectMeetingWS(
    meetingId: string,
    onMessage: (message: any) => void,
  ): () => void {
    let ws: WebSocket | null = null;
    let pingInterval: ReturnType<typeof setInterval> | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    // Exponential backoff (2s → 15s cap) so a backend restart or deploy
    // produces a couple of quiet retries, not a console full of failures.
    let reconnectDelay = 2000;

    const connect = () => {
      if (closed) return;
      const token = this.getToken();
      const qs = token ? `?token=${encodeURIComponent(token)}` : '';
      ws = new WebSocket(`${this.wsUrl}/api/v1/meetings/${meetingId}/ws${qs}`);

      ws.onopen = () => {
        console.log(`[MeetingWS] connected to ${meetingId.slice(0, 8)}`);
        reconnectDelay = 2000; // healthy again — reset the backoff
        pingInterval = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send('ping');
        }, 25000);
      };

      ws.onmessage = (event) => {
        if (event.data === 'pong') return;
        try {
          onMessage(JSON.parse(event.data));
        } catch (e) {
          console.warn('[MeetingWS] parse error', e);
        }
      };

      ws.onclose = () => {
        if (pingInterval) {
          clearInterval(pingInterval);
          pingInterval = null;
        }
        if (!closed) {
          reconnectTimer = setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 2, 15000);
        }
      };

      ws.onerror = () => {
        // onclose will fire next; reconnect happens there
      };
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingInterval) clearInterval(pingInterval);
      if (ws) {
        // Detach handlers so this teardown can't trigger a reconnect.
        ws.onclose = null;
        ws.onerror = null;
        if (ws.readyState === WebSocket.CONNECTING) {
          // Closing a CONNECTING socket logs a benign browser warning
          // ("closed before the connection is established") — common under
          // React StrictMode's mount/unmount. Wait for open, then close cleanly.
          ws.onopen = () => { try { ws?.close(); } catch {} };
        } else {
          try { ws.close(); } catch {}
        }
      }
    };
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
        // Closing a still-CONNECTING socket logs a benign browser warning
        // ("closed before the connection is established") under React
        // StrictMode's mount/unmount. Defer the close until it opens.
        if (currentWs.readyState === WebSocket.CONNECTING) {
          currentWs.onopen = () => { try { currentWs.close(); } catch {} };
        } else {
          try { currentWs.close(); } catch {}
        }
      },
    };
  }
}

// Export singleton instance
export const apiClient = new ApiClient();
