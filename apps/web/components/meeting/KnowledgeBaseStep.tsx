'use client';

import React, { useState, useEffect } from 'react';
import { Upload, FileText, Trash2, CheckCircle, ChevronRight, Network, Layers } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import KnowledgeGraphView from './KnowledgeGraphView';
import DocumentElementsView from './DocumentElementsView';

type DetailTab = 'graph' | 'elements';

export default function KnowledgeBaseStep() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('graph');

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

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await apiClient.uploadDocument(file, true);
      }
      fetchDocs();
    } catch (error) {
      console.error('Upload failed:', error);
    } finally {
      setUploading(false);
    }
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
        Upload company documents, reports, or meeting materials. These will be available to AI agents
        during your meeting for context-aware answers.
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
                      <p className="text-xs text-gray-500">
                        {doc.chunk_count > 0
                          ? `${doc.chunk_count} chunks`
                          : doc.processing_status}
                      </p>
                    </div>
                  </button>
                  <div className="flex items-center gap-2">
                    {doc.processing_status === 'completed' ? (
                      <CheckCircle className="w-4 h-4 text-green-500" />
                    ) : doc.processing_status === 'processing' ? (
                      <div className="w-4 h-4 border-2 border-[#4f46e5] border-t-transparent rounded-full animate-spin" />
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
