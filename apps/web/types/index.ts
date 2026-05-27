// Type definitions for Voice Document Intelligence System

export interface Document {
  id: string;
  filename: string;
  content_type: string;
  file_size: number;
  file_path: string;
  file_hash?: string;
  uploaded_at: string;
  processing_status: 'pending' | 'processing' | 'completed' | 'failed';
  use_enhanced: boolean;
  storage_type?: string;
  chunk_count?: number;
  structure?: DocumentStructure;
  processed_at?: string;
  processing_method?: 'basic' | 'enhanced_contextual';
  error?: string;
}

export interface DocumentStructure {
  title: string;
  sections: Section[];
  hierarchy: Record<string, number[]>;
  total_pages: number;
  total_chunks: number;
  document_type: string;
  summary?: string;
  key_topics?: string[];
}

export interface Section {
  heading: string;
  content: string;
  level: number;
  start_line?: number;
}

export interface QueryRequest {
  query: string;
  conversation_id?: string;
  context_level?: 'local' | 'document' | 'global';
  max_results?: number;
  use_enhanced?: boolean;
}

export interface QueryResponse {
  answer: string;
  sources: Source[];
  conversation_id: string;
  context_level: string;
  metadata: {
    metrics?: LatencyMetrics;
    context_info?: Record<string, any>;
  };
}

export interface Source {
  document_id: string;
  chunk_id: string;
  content: string;
  score: number;
  metadata?: Record<string, any>;
}

export interface LatencyMetrics {
  vad_latency?: number;
  stt_latency: number;
  llm_latency: number;
  tts_latency: number;
  rag_latency: number;
  embedding_latency?: number;
  total_latency: number;
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: {
    database: string;
    redis: string;
    qdrant: string;
    embeddings: string;
    voice: string;
  };
  version: string;
  timestamp: string;
}

export interface UsageAnalytics {
  documents: {
    total: number;
    completed: number;
    failed: number;
    processing: number;
  };
  chunks: {
    total: number;
    average_per_doc: number;
  };
  processing_methods: {
    enhanced_contextual: number;
    basic: number;
  };
  timestamp: string;
}

export interface PerformanceAnalytics {
  average_latencies: {
    stt: number;
    llm: number;
    tts: number;
    rag: number;
    total: number;
  };
  success_rate: number;
  active_sessions: number;
  timestamp: string;
}

export interface VoiceToken {
  token: string;
  url: string;
  room_name: string;
}

export interface WebSocketMessage {
  type: 'document_uploaded' | 'processing_started' | 'processing_completed' | 'processing_failed' | 'document_deleted';
  document_id?: string;
  filename?: string;
  chunk_count?: number;
  error?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources?: Source[];
  latency?: number;
}

export interface ConversationHistory {
  conversation_id: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

// Donna — meeting domain types

export interface Meeting {
  id: string;
  title: string;
  description?: string;
  status: string;
  scheduled_at?: string;
  started_at?: string;
  ended_at?: string;
  attendees: { name?: string; email?: string }[];
  created_at: string;
  research?: ResearchBriefData | null;
  nudges?: NudgeData[];
  decisions?: DecisionData[];
  summary?: MeetingSummaryData | null;
}

export interface ResearchBriefData {
  status: string;
  source_count: number;
  executive_summary?: string;
  topics: ResearchTopic[];
}

export interface ResearchTopic {
  topic: string;
  rationale: string;
  sources: ResearchSource[];
}

export interface ResearchSource {
  url: string;
  title: string;
  excerpt: string;
  tier: number;
  credibility_score: number;
}

export interface NudgeData {
  id: string;
  type: string;
  title: string;
  content: string;
  source_agent?: string;
  relevance_score?: number;
  created_at: string;
}

export interface DecisionData {
  id: string;
  decision_text: string;
  owner?: string;
  deadline?: string;
  status: string;
  action_items?: ActionItemData[];
}

export interface ActionItemData {
  id: string;
  description: string;
  assignee?: string;
  priority: string;
  status: string;
}

export interface MeetingSummaryData {
  summary_text: string;
  key_insights: any[];
  email_sent_at?: string;
}
