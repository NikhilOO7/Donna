'use client';

import React, { useEffect, useState } from 'react';
import { FileText, Trash2, Clock, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { Document } from '@/types';
import { formatBytes, formatRelativeTime, getStatusColor, getFileIcon } from '@/lib/utils';

interface DocumentListProps {
  refreshTrigger?: number;
  onDocumentSelect?: (document: Document) => void;
}

export default function DocumentList({ refreshTrigger, onDocumentSelect }: DocumentListProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiClient.listDocuments(0, 50);
      setDocuments(result.documents);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [refreshTrigger]);

  const handleDelete = async (documentId: string, event: React.MouseEvent) => {
    event.stopPropagation();

    if (!confirm('Are you sure you want to delete this document?')) {
      return;
    }

    try {
      setDeletingId(documentId);
      await apiClient.deleteDocument(documentId);
      setDocuments(docs => docs.filter(doc => doc.id !== documentId));
    } catch (err: any) {
      alert(err.response?.data?.error || 'Failed to delete document');
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-5 h-5 text-green-600" />;
      case 'processing':
        return <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />;
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-600" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      default:
        return <FileText className="w-5 h-5 text-gray-600" />;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
        <XCircle className="w-8 h-8 text-red-600 mx-auto mb-2" />
        <p className="text-red-900 font-medium">Failed to load documents</p>
        <p className="text-red-700 text-sm mt-1">{error}</p>
        <button
          onClick={fetchDocuments}
          className="mt-3 text-sm text-red-700 hover:text-red-800 underline"
        >
          Try again
        </button>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="text-center py-12">
        <FileText className="w-12 h-12 text-gray-400 mx-auto mb-3" />
        <p className="text-gray-600">No documents uploaded yet</p>
        <p className="text-gray-500 text-sm mt-1">Upload your first document to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {documents.map((doc) => (
        <div
          key={doc.id}
          onClick={() => onDocumentSelect?.(doc)}
          className={`
            bg-white border border-gray-200 rounded-lg p-4
            hover:border-primary-300 hover:shadow-md
            transition-all duration-200 cursor-pointer
            ${deletingId === doc.id ? 'opacity-50 pointer-events-none' : ''}
          `}
        >
          <div className="flex items-start justify-between gap-4">
            {/* Document Info */}
            <div className="flex items-start gap-3 flex-1 min-w-0">
              <div className="text-2xl mt-1">
                {getFileIcon(doc.file_type || doc.content_type)}
              </div>

              <div className="flex-1 min-w-0">
                <h3 className="font-medium text-gray-900 truncate">
                  {doc.filename}
                </h3>

                <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                  <span>{formatBytes(doc.file_size)}</span>
                  <span>•</span>
                  <span>{formatRelativeTime(doc.uploaded_at)}</span>
                  {doc.chunk_count && (
                    <>
                      <span>•</span>
                      <span>{doc.chunk_count} chunks</span>
                    </>
                  )}
                </div>

                {/* Processing Method Badge */}
                {doc.processing_method === 'enhanced_contextual' && (
                  <div className="inline-flex items-center gap-1 mt-2 px-2 py-0.5 bg-primary-50 text-primary-700 text-xs font-medium rounded">
                    ⚡ Enhanced Processing
                  </div>
                )}
              </div>
            </div>

            {/* Status & Actions */}
            <div className="flex items-center gap-3">
              {/* Status */}
              <div className={`
                inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border
                ${getStatusColor(doc.processing_status)}
              `}>
                {getStatusIcon(doc.processing_status)}
                <span className="capitalize">{doc.processing_status}</span>
              </div>

              {/* Delete Button */}
              <button
                onClick={(e) => handleDelete(doc.id, e)}
                disabled={deletingId === doc.id}
                className="p-2 hover:bg-red-50 rounded-lg transition-colors group"
                title="Delete document"
              >
                {deletingId === doc.id ? (
                  <Loader2 className="w-5 h-5 text-red-600 animate-spin" />
                ) : (
                  <Trash2 className="w-5 h-5 text-gray-400 group-hover:text-red-600" />
                )}
              </button>
            </div>
          </div>

          {/* Error Message */}
          {doc.error && (
            <div className="mt-3 pt-3 border-t border-gray-100">
              <p className="text-sm text-red-600">
                <span className="font-medium">Error:</span> {doc.error}
              </p>
            </div>
          )}

          {/* Summary */}
          {doc.structure?.summary && doc.processing_status === 'completed' && (
            <div className="mt-3 pt-3 border-t border-gray-100">
              <p className="text-sm text-gray-600 line-clamp-2">
                {doc.structure.summary}
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
