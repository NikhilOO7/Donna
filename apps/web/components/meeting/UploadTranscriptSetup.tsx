'use client';

import React, { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  X, Sparkles, Loader2, FileUp, Check, FileText,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface UploadTranscriptSetupProps {
  onClose: () => void;
  onCreated: () => void;
}

const MEETING_TYPES = [
  'Strategy Planning', 'Design Sync', 'Product Review', 'Engineering Sync',
  'Go-to-Market Planning', 'Vendor / Partner Review', 'Other',
];

/** Client-side preview parser — mirrors the server's rules. */
function parsePreview(text: string): { speaker: string; text: string }[] {
  const tsLine = /^\s*(\d+\s*$|WEBVTT|\d{1,2}:\d{2}(:\d{2})?[.,]?\d*\s*-->\s*.*)/i;
  const leadingTs = /^\s*[[(]?\d{1,2}:\d{2}(:\d{2})?[\])]?\s*/;
  const speakerLine = /^([A-Za-z][\w .'-]{0,60}?)\s*:\s+(.+)$/;

  const out: { speaker: string; text: string }[] = [];
  for (const raw of (text || '').split('\n')) {
    let line = raw.trim();
    if (!line || tsLine.test(line)) continue;
    line = line.replace(leadingTs, '').trim();
    if (!line) continue;
    const m = speakerLine.exec(line);
    if (m) {
      out.push({ speaker: m[1].trim(), text: m[2].trim() });
    } else if (out.length > 0) {
      out[out.length - 1].text += ' ' + line;
    } else {
      out.push({ speaker: 'Speaker', text: line });
    }
  }
  return out.filter((u) => u.text);
}

export default function UploadTranscriptSetup({ onClose, onCreated }: UploadTranscriptSetupProps) {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [meetingType, setMeetingType] = useState('');
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const preview = useMemo(() => parsePreview(text), [text]);
  const speakers = useMemo(
    () => Array.from(new Set(preview.map((u) => u.speaker))),
    [preview],
  );

  const handleFile = async (f: File | null) => {
    if (!f) return;
    if (f.size > 500_000) {
      setError('File too large (max 500KB)');
      return;
    }
    setFileName(f.name);
    setError(null);
    setText(await f.text());
    if (!title) setTitle(f.name.replace(/\.(txt|vtt|srt)$/i, ''));
  };

  const analyze = async () => {
    if (preview.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiClient.importTranscript({
        transcript_text: text,
        title: title.trim() || undefined,
        meeting_type: meetingType || undefined,
      });
      onCreated();
      router.push(`/meetings/${result.id}`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Import failed — please try again.');
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-white overflow-y-auto">
      {/* Top bar */}
      <div className="sticky top-0 bg-white/90 backdrop-blur-sm border-b border-gray-100 z-10">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
              <FileUp className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-semibold text-gray-900 text-sm">Upload Transcript</span>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">
            Analyze an existing meeting
          </h1>
          <p className="text-sm text-gray-500 max-w-lg mx-auto">
            Paste a transcript or upload a file. Donna will attribute speakers,
            extract decisions and action items, and write the summary — as if
            she&apos;d been in the room.
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* LEFT: input */}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Meeting name
                </label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Q2 Vendor Review"
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Meeting type
                </label>
                <select
                  value={meetingType}
                  onChange={(e) => setMeetingType(e.target.value)}
                  className={`w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow ${meetingType ? 'text-gray-900' : 'text-gray-400'}`}
                >
                  <option value="">Optional</option>
                  {MEETING_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* File upload */}
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                handleFile(e.dataTransfer.files?.[0] || null);
              }}
              className="border-2 border-dashed border-gray-200 hover:border-indigo-300 rounded-xl p-5 text-center cursor-pointer transition-colors"
            >
              <FileUp className="w-6 h-6 text-gray-400 mx-auto mb-1.5" />
              <p className="text-sm text-gray-600">
                {fileName || 'Drop a .txt, .vtt, or .srt file — or click to browse'}
              </p>
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.vtt,.srt,text/plain"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0] || null)}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                Or paste the transcript
              </label>
              <textarea
                value={text}
                onChange={(e) => { setText(e.target.value); setError(null); }}
                placeholder={'Alice: Let\'s kick off the vendor review.\nBob: The Beacon quote came in 12% under budget.\nAlice: Then let\'s go with Beacon — decided.'}
                rows={12}
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[13px] font-mono focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none resize-none transition-shadow"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-3.5 py-2.5">
                {error}
              </p>
            )}

            <button
              onClick={analyze}
              disabled={preview.length === 0 || busy}
              className="w-full flex items-center justify-center gap-2 py-3 bg-gray-900 hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-xl text-sm font-semibold shadow-md hover:shadow-lg disabled:shadow-none transition-all duration-200"
            >
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Importing &amp; analyzing…
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Analyze with Donna
                </>
              )}
            </button>
            <p className="text-[11px] text-gray-400 text-center">
              Donna creates the meeting, attributes every line, and generates the
              summary automatically.
            </p>
          </div>

          {/* RIGHT: parsed preview */}
          <div className="flex flex-col bg-white rounded-2xl border border-gray-200/80 shadow-card overflow-hidden min-h-[420px]">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60 flex items-center justify-between">
              <p className="text-xs font-bold uppercase tracking-wider text-gray-400">
                Parsed Preview
              </p>
              {preview.length > 0 && (
                <span className="text-[11px] text-gray-400">
                  {preview.length} utterances · {speakers.length}{' '}
                  {speakers.length === 1 ? 'speaker' : 'speakers'}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2 max-h-[520px]">
              {preview.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center text-gray-400 py-14">
                  <FileText className="w-8 h-8 text-gray-200 mb-3" />
                  <p className="text-sm font-medium text-gray-500">Nothing parsed yet</p>
                  <p className="text-xs text-gray-400 mt-1 max-w-[240px]">
                    As you paste, Donna shows exactly how she&apos;ll read the
                    conversation — speaker by speaker.
                  </p>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-1.5 flex-wrap pb-1">
                    {speakers.map((sp) => (
                      <span key={sp} className="px-2 py-0.5 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-full text-[11px] font-medium">
                        {sp}
                      </span>
                    ))}
                    <span className="flex items-center gap-1 text-[11px] text-emerald-600 ml-auto">
                      <Check className="w-3 h-3" /> ready to analyze
                    </span>
                  </div>
                  {preview.slice(0, 200).map((u, i) => (
                    <div key={i} className="px-3 py-2 rounded-lg bg-gray-50/80 border border-gray-100 text-[13px]">
                      <span className="font-semibold text-indigo-600">{u.speaker}:</span>{' '}
                      <span className="text-gray-700">{u.text}</span>
                    </div>
                  ))}
                  {preview.length > 200 && (
                    <p className="text-[11px] text-gray-400 text-center pt-1">
                      … and {preview.length - 200} more
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
