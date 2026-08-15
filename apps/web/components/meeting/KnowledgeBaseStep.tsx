'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Upload, FileText, Trash2, CheckCircle, ChevronRight, Network, Layers, AlertCircle } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import KnowledgeGraphView from './KnowledgeGraphView';
import DocumentElementsView from './DocumentElementsView';

type DetailTab = 'graph' | 'elements';

type Notice = { kind: 'info' | 'error'; text: string } | null;


/** Human-readable reason a document failed, with the next action.
 *
 * `processing_error` holds the raw provider/pipeline error. Showing it raw is
 * noise; hiding it entirely is what left "failed" meaning nothing at all. So:
 * translate the cases we recognise, fall back to the raw text otherwise. */
function docErrorText(doc: any): string {
  const raw =
    typeof doc.processing_error === 'string'
      ? doc.processing_error
      : doc.processing_error?.message || doc.processing_error?.error || '';
  const s = String(raw);
  if (/insufficient_quota|credit_balance_exhausted|no credits/i.test(s))
    return 'Failed — OpenAI credits exhausted. Add credits, then re-upload.';
  if (/429|rate.?limit/i.test(s))
    return 'Failed — provider rate limit. Try again shortly.';
  if (/timeout|timed out/i.test(s))
    return 'Failed — processing timed out. Try a smaller file.';
  if (/unsupported|not supported|cannot parse/i.test(s))
    return 'Failed — unsupported or unreadable file format.';
  return s ? `Failed — ${s.slice(0, 120)}` : 'Failed — see server logs for the reason.';
}

export default function KnowledgeBaseStep({ meetingId }: { meetingId?: string }) {
  const [documents, setDocuments] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('graph');
  const [notice, setNotice] = useState<Notice>(null);

  const fetchDocs = async () => {
    try {
      const data = await apiClient.listDocuments(0, 20);
      setDocuments(data.documents || []);
    } catch (error) {
      console.error('Failed to load documents:', error);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  // Poll while any document is still processing so spinners resolve on their
  // own. Backoff after a minute: big PDFs legitimately take a while, but a
  // stuck backend must never turn the browser into a 4s battering ram.
  const hasProcessing = documents.some((d) => d.processing_status === 'processing');
  const pollCount = useRef(0);
  useEffect(() => {
    if (!hasProcessing) {
      pollCount.current = 0;
      return;
    }
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      pollCount.current += 1;
      fetchDocs();
      const delay = pollCount.current < 15 ? 4000 : 15000;
      timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, 4000);
    return () => clearTimeout(timer);
  }, [hasProcessing]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setNotice(null);
    const duplicates: string[] = [];
    const failures: string[] = [];
    for (const file of Array.from(files)) {
      try {
        await apiClient.uploadDocument(file, true, meetingId);
      } catch (error: any) {
        if (error?.response?.status === 409) {
          duplicates.push(file.name);
        } else {
          console.error('Upload failed:', error);
          failures.push(file.name);
        }
      }
    }
    if (failures.length > 0) {
      setNotice({ kind: 'error', text: `Upload failed for: ${failures.join(', ')}` });
    } else if (duplicates.length > 0) {
      setNotice({
        kind: 'info',
        text: `Already in your knowledge base: ${duplicates.join(', ')}`,
      });
    }
    fetchDocs();
    setUploading(false);
  };

  const handleDelete = async (docId: string) => {
    try {
      await apiClient.deleteDocument(docId);
      fetchDocs();
    } catch (error) {
      console.error('Delete failed:', error);
    }
  };

  const completedDocs = documents.filter((d) => d.processing_status === 'completed');

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Upload company documents, reports, or meeting materials.
        {meetingId
          ? ' Files uploaded here are attached to this meeting — Donna ranks them ahead of your general knowledge base.'
          : ' These will be available to AI agents during your meeting for context-aware answers.'}
      </p>

      {/* Compact Upload Area */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleUpload(e.dataTransfer.files);
        }}
        className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
          dragOver
            ? 'border-primary-400 bg-primary-50'
            : 'border-gray-200 hover:border-gray-300'
        }`}
      >
        <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2" />
        <p className="text-sm text-gray-600 mb-1">
          {uploading ? 'Uploading...' : 'Drag & drop files or click to browse'}
        </p>
        <p className="text-xs text-gray-400">PDF, DOCX, TXT (max 100MB)</p>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt"
          onChange={(e) => handleUpload(e.target.files)}
          className="hidden"
          id="kb-upload"
        />
        <label
          htmlFor="kb-upload"
          className="inline-block mt-3 px-4 py-2 bg-primary-600 text-white text-sm rounded-lg hover:bg-primary-700 cursor-pointer transition-colors"
        >
          Browse Files
        </label>
      </div>

      {/* Upload notice */}
      {notice && (
        <div
          className={`px-3.5 py-2.5 rounded-lg text-sm border ${
            notice.kind === 'error'
              ? 'bg-red-50 border-red-200 text-red-700'
              : 'bg-blue-50 border-blue-200 text-blue-700'
          }`}
        >
          {notice.text}
        </div>
      )}

      {/* Document List */}
      {documents.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-700">
            Uploaded Documents ({completedDocs.length} ready)
          </h4>
          {documents.map((doc) => {
            const isExpanded = expandedDoc === doc.id;
            const isReady = doc.processing_status === 'completed';
            return (
              <div key={doc.id} className="bg-gray-50 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between p-3">
                  <button
                    onClick={() => isReady && setExpandedDoc(isExpanded ? null : doc.id)}
                    disabled={!isReady}
                    className="flex items-center gap-3 min-w-0 flex-1 text-left disabled:cursor-default"
                  >
                    <ChevronRight
                      className={`w-4 h-4 text-gray-400 flex-shrink-0 transition-transform ${
                        isExpanded ? 'rotate-90' : ''
                      } ${!isReady ? 'opacity-30' : ''}`}
                    />
                    <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                      {/* A bare "failed" tells the user nothing actionable. The
                          backend records why (quota, OCR, unsupported format) —
                          surface it, and say what to do next. */}
                      {doc.processing_status === 'failed' ? (
                        <p className="text-xs text-red-600 truncate" title={docErrorText(doc)}>
                          {docErrorText(doc)}
                        </p>
                      ) : (
                        <p className="text-xs text-gray-500">
                          {doc.chunk_count > 0
                            ? `${doc.chunk_count} chunks`
                            : doc.processing_status}
                        </p>
                      )}
                    </div>
                  </button>
                  <div className="flex items-center gap-2">
                    {doc.processing_status === 'completed' ? (
                      <CheckCircle className="w-4 h-4 text-green-500" />
                    ) : doc.processing_status === 'processing' ? (
                      <div className="w-4 h-4 border-2 border-[#4f46e5] border-t-transparent rounded-full animate-spin" />
                    ) : doc.processing_status === 'failed' ? (
                      <AlertCircle className="w-4 h-4 text-red-500" />
                    ) : null}
                    <button
                      onClick={() => handleDelete(doc.id)}
                      className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {isExpanded && isReady && (
                  <div className="border-t border-gray-200 bg-white p-3 space-y-3">
                    <div className="flex gap-1 text-xs">
                      <button
                        onClick={() => setDetailTab('graph')}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors ${
                          detailTab === 'graph'
                            ? 'bg-indigo-100 text-indigo-700'
                            : 'text-gray-500 hover:bg-gray-100'
                        }`}
                      >
                        <Network className="w-3 h-3" />
                        Knowledge Graph
                      </button>
                      <button
                        onClick={() => setDetailTab('elements')}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors ${
                          detailTab === 'elements'
                            ? 'bg-indigo-100 text-indigo-700'
                            : 'text-gray-500 hover:bg-gray-100'
                        }`}
                      >
                        <Layers className="w-3 h-3" />
                        Tables & Images
                      </button>
                    </div>
                    {detailTab === 'graph' ? (
                      <KnowledgeGraphView documentId={doc.id} />
                    ) : (
                      <DocumentElementsView documentId={doc.id} />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
