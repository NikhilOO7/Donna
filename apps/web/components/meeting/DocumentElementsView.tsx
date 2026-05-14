'use client';

/**
 * DocumentElementsView
 *
 * Lists tables, images, and charts extracted from a PDF by the
 * enhanced document pipeline. Tables render as markdown blocks;
 * images show OCR/caption text.
 */

import React, { useEffect, useState } from 'react';
import { Table, Image as ImageIcon, Loader2, Layers } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface DocumentElement {
  id: string;
  type: 'table' | 'image' | 'chart' | string;
  content: string;
  page?: number | null;
  caption?: string | null;
  raw_data?: any;
}

interface Props {
  documentId: string;
}

export default function DocumentElementsView({ documentId }: Props) {
  const [elements, setElements] = useState<DocumentElement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiClient
      .getDocumentElements(documentId)
      .then((data) => {
        if (!cancelled) setElements(data.elements || []);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || 'Failed to load elements');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6 text-gray-400 text-sm">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        Scanning extracted elements...
      </div>
    );
  }

  if (error) {
    return <div className="py-3 text-sm text-red-500">{error}</div>;
  }

  if (elements.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-gray-400">
        <Layers className="w-6 h-6 mx-auto mb-1 opacity-40" />
        No tables or images extracted (text-only document)
      </div>
    );
  }

  const tables = elements.filter((e) => e.type === 'table');
  const images = elements.filter((e) => e.type === 'image' || e.type === 'chart');

  return (
    <div className="space-y-4">
      {tables.length > 0 && (
        <section>
          <h5 className="flex items-center gap-1.5 text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
            <Table className="w-3.5 h-3.5 text-indigo-600" />
            Tables ({tables.length})
          </h5>
          <div className="space-y-2">
            {tables.map((t) => (
              <div
                key={t.id}
                className="rounded-lg border border-slate-200 bg-white"
              >
                <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-100 text-[11px] text-gray-500">
                  <span>
                    {t.raw_data?.row_count ?? '?'} rows ×{' '}
                    {t.raw_data?.col_count ?? '?'} cols
                  </span>
                  {t.page != null && <span>Page {t.page}</span>}
                </div>
                <pre className="overflow-x-auto text-[11px] leading-relaxed text-gray-700 p-3 font-mono whitespace-pre">
                  {t.content.slice(0, 800)}
                  {t.content.length > 800 ? '\n…' : ''}
                </pre>
              </div>
            ))}
          </div>
        </section>
      )}

      {images.length > 0 && (
        <section>
          <h5 className="flex items-center gap-1.5 text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
            <ImageIcon className="w-3.5 h-3.5 text-pink-600" />
            Images & Charts ({images.length})
          </h5>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {images.map((im) => (
              <div
                key={im.id}
                className="rounded-lg border border-slate-200 bg-white p-3"
              >
                <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1.5">
                  <span className="capitalize">{im.type}</span>
                  {im.page != null && <span>Page {im.page}</span>}
                </div>
                <p className="text-[12px] text-gray-700 leading-relaxed line-clamp-4">
                  {im.content || im.caption || '(no description available)'}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
