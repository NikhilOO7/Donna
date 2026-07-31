'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft, Mic, Users, Volume2, CheckCircle2, Check, Plus,
  Sparkles, Loader2, AlertTriangle, X,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface VoiceSetupWizardProps {
  meeting: any;
  onClose: () => void;
  /** Called when the user hits "Start Meeting with Donna" on the final screen. */
  onComplete: () => void;
}

type Step = 'prepare' | 'ready' | 'mic' | 'participants' | 'done';

type Participant = {
  name: string;
  email?: string;
  registered: boolean;
  expertise: string[];
};

const LEVEL_THRESHOLD = 8; // 0-100 scale — voice comfortably above room noise

export default function VoiceSetupWizard({ meeting, onClose, onComplete }: VoiceSetupWizardProps) {
  const [step, setStep] = useState<Step>('prepare');

  /* ---------------- Microphone engine (real getUserMedia + analyser) ------- */
  const [micStatus, setMicStatus] = useState<'idle' | 'requesting' | 'active' | 'denied'>('idle');
  const [level, setLevel] = useState(0);
  const levelRef = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const [micWorking, setMicWorking] = useState(false);

  const stopMic = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
    setLevel(0);
  }, []);

  const startMic = useCallback(async () => {
    if (streamRef.current) return; // already running
    setMicStatus('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      const Ctx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new Ctx();
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        const pct = Math.min(100, Math.round((avg / 140) * 100));
        levelRef.current = pct;
        setLevel(pct);
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
      setMicStatus('active');
    } catch (err) {
      console.error('Mic access failed:', err);
      setMicStatus('denied');
    }
  }, []);

  // Mark the mic as working the first time speech clears the threshold
  useEffect(() => {
    if (step === 'mic' && micStatus === 'active' && level > LEVEL_THRESHOLD) {
      setMicWorking(true);
    }
  }, [level, step, micStatus]);

  useEffect(() => () => stopMic(), [stopMic]);

  /* ------------------------ Participants registration ---------------------- */
  const [participants, setParticipants] = useState<Participant[]>(() =>
    (meeting.attendees || [])
      .map((a: any) => ({
        name: a?.name || a?.email || '',
        email: a?.email,
        registered: Boolean(a?.voice_registered),
        expertise: Array.isArray(a?.expertise) ? a.expertise : [],
      }))
      .filter((p: Participant) => p.name),
  );
  const [nameInput, setNameInput] = useState('');
  const [expertiseInput, setExpertiseInput] = useState('');
  const [recording, setRecording] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const parseExpertise = () =>
    expertiseInput
      .split(',')
      .map((e) => e.trim())
      .filter(Boolean)
      .slice(0, 8);

  const recordVoiceCheck = async () => {
    const name = nameInput.trim();
    if (!name || recording) return;
    setRecording(true);
    setRecordError(null);

    // Sample the live level for ~2.5s and look for voice activity
    let peak = 0;
    const samples = 25;
    for (let i = 0; i < samples; i++) {
      await new Promise((r) => setTimeout(r, 100));
      peak = Math.max(peak, levelRef.current);
    }
    setRecording(false);

    if (peak > LEVEL_THRESHOLD) {
      setParticipants((prev) => [
        ...prev.filter((p) => p.name !== name),
        { name, registered: true, expertise: parseExpertise() },
      ]);
      setNameInput('');
      setExpertiseInput('');
    } else {
      setRecordError("Didn't catch that — speak a full sentence while recording.");
    }
  };

  const addWithoutCheck = () => {
    const name = nameInput.trim();
    if (!name) return;
    setParticipants((prev) => [
      ...prev.filter((p) => p.name !== name),
      { name, registered: false, expertise: parseExpertise() },
    ]);
    setNameInput('');
    setExpertiseInput('');
    setRecordError(null);
  };

  const completeRegistration = async () => {
    setSaving(true);
    try {
      await apiClient.updateMeetingAttendees(
        meeting.id,
        participants.map((p) => ({
          name: p.name,
          ...(p.email ? { email: p.email } : {}),
          ...(p.registered ? { voice_registered: true } : {}),
          ...(p.expertise.length > 0 ? { expertise: p.expertise } : {}),
        })),
      );
      setStep('done');
    } catch (error) {
      console.error('Failed to save participants:', error);
      setRecordError('Could not save participants — please try again.');
    } finally {
      setSaving(false);
    }
  };

  const finish = () => {
    stopMic();
    onComplete();
  };

  const handleClose = () => {
    stopMic();
    onClose();
  };

  /* --------------------------------- Header -------------------------------- */
  const backTarget: Partial<Record<Step, { label: string; to: Step }>> = {
    ready: { label: 'Back to Options', to: 'prepare' },
    mic: { label: 'Back', to: 'ready' },
    participants: { label: 'Back to Mic Test', to: 'mic' },
    done: { label: 'Back to Mic Test', to: 'participants' },
  };
  const back = backTarget[step];

  /* --------------------------------- Screens ------------------------------- */
  return (
    <div className="fixed inset-0 z-50 bg-white overflow-y-auto">
      {/* Top bar */}
      <div className="sticky top-0 bg-white/90 backdrop-blur-sm border-b border-gray-100 z-10">
        <div className="max-w-3xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-4">
            {back ? (
              <button
                onClick={() => setStep(back.to)}
                className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                {back.label}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
                  <Sparkles className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="font-semibold text-gray-900 text-sm">Donna</span>
              </div>
            )}
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            title="Close setup"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="max-w-xl mx-auto px-6 py-12">
        {/* ---- 1. Prepare for Voice Registration ---- */}
        {step === 'prepare' && (
          <div className="animate-fade-up">
            <h1 className="text-2xl font-bold text-gray-900 text-center mb-4">
              Prepare for Voice Registration
            </h1>
            <p className="text-sm text-gray-500 text-center leading-relaxed mb-2 max-w-md mx-auto">
              In the next step, we&apos;ll check your microphone and register each
              meeting participant. This helps Donna attribute who&apos;s speaking
              during your meeting.
            </p>
            <p className="text-sm text-gray-500 text-center mb-8">
              Let&apos;s make sure everything is set up correctly before we begin.
            </p>

            <div className="space-y-3 mb-10">
              {[
                {
                  icon: Mic,
                  title: 'Audio Check',
                  body: "We'll first test your microphone to ensure it's properly connected and working.",
                },
                {
                  icon: Users,
                  title: 'Participants Ready',
                  body: 'Ensure all meeting participants are present to register their names and voices.',
                },
                {
                  icon: Volume2,
                  title: 'Quiet Environment',
                  body: 'Find a quiet place for optimal voice detection results.',
                },
              ].map((item) => (
                <div key={item.title} className="flex items-start gap-3.5 p-4 bg-gray-50 rounded-xl">
                  <item.icon className="w-[18px] h-[18px] text-gray-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{item.title}</p>
                    <p className="text-[13px] text-gray-500 mt-0.5">{item.body}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-center gap-3">
              <button
                onClick={handleClose}
                className="flex items-center gap-1.5 px-5 py-2.5 text-gray-600 border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors text-sm font-medium"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back
              </button>
              <button
                onClick={() => setStep('ready')}
                className="px-6 py-2.5 bg-gray-900 hover:bg-gray-800 text-white rounded-xl text-sm font-medium shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
              >
                Continue to Mic Test
              </button>
            </div>
          </div>
        )}

        {/* ---- 2. Let's Get Ready ---- */}
        {step === 'ready' && (
          <div className="text-center animate-fade-up">
            <div className="w-20 h-20 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-8">
              <Mic className="w-9 h-9 text-gray-700" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900 mb-3">Let&apos;s Get Ready</h1>
            <p className="text-sm text-gray-500 mb-10 max-w-sm mx-auto leading-relaxed">
              Donna needs to check your microphone and register participants for
              your upcoming meeting.
            </p>

            <div className="border border-gray-200 rounded-xl py-6 px-8 mb-10">
              <p className="text-sm font-semibold text-gray-900">Meeting Details</p>
              <p className="text-sm text-gray-500 mt-1">{meeting.title || 'Untitled Meeting'}</p>
            </div>

            <button
              onClick={() => { startMic(); setStep('mic'); }}
              className="px-6 py-3 bg-gray-900 hover:bg-gray-800 text-white rounded-xl text-sm font-medium shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
            >
              Continue to Microphone Check
            </button>
            <p className="text-xs text-gray-400 mt-5">
              Donna will guide you through microphone setup and participant registration.
            </p>
          </div>
        )}

        {/* ---- 3. Microphone check (live meter) ---- */}
        {step === 'mic' && (
          <div className="text-center animate-fade-up">
            <h1 className="text-2xl font-bold text-gray-900 mb-3">Microphone Check</h1>
            <p className="text-sm text-gray-500 mb-10 max-w-sm mx-auto">
              Say something out loud — we&apos;re listening for your voice.
            </p>

            {micStatus === 'denied' ? (
              <div className="p-6 bg-red-50 border border-red-100 rounded-2xl mb-8">
                <AlertTriangle className="w-6 h-6 text-red-500 mx-auto mb-3" />
                <p className="text-sm font-medium text-red-700 mb-1">Microphone access blocked</p>
                <p className="text-xs text-red-500 mb-4">
                  Allow microphone access in your browser&apos;s address bar, then try again.
                </p>
                <button
                  onClick={() => { setMicStatus('idle'); startMic(); }}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-medium transition-colors"
                >
                  Try again
                </button>
              </div>
            ) : (
              <>
                {/* Live level meter */}
                <div className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 transition-all duration-200 ${
                  micWorking ? 'bg-emerald-50 ring-2 ring-emerald-200' : 'bg-gray-100'
                }`}
                  style={{
                    boxShadow: micStatus === 'active' ? `0 0 0 ${Math.min(level, 40) / 2.5}px rgba(99,102,241,0.12)` : undefined,
                  }}
                >
                  {micStatus === 'requesting' ? (
                    <Loader2 className="w-8 h-8 text-gray-400 animate-spin" />
                  ) : micWorking ? (
                    <CheckCircle2 className="w-9 h-9 text-emerald-500" />
                  ) : (
                    <Mic className="w-8 h-8 text-gray-600" />
                  )}
                </div>

                <div className="flex items-end justify-center gap-1 h-10 mb-4">
                  {Array.from({ length: 24 }, (_, i) => {
                    const active = level > (i / 24) * 100;
                    return (
                      <span
                        key={i}
                        className={`w-1.5 rounded-full transition-all duration-75 ${
                          active ? 'bg-indigo-500' : 'bg-gray-200'
                        }`}
                        style={{ height: `${8 + (i % 5) * 6}px` }}
                      />
                    );
                  })}
                </div>

                <p className={`text-sm mb-10 ${micWorking ? 'text-emerald-600 font-medium' : 'text-gray-400'}`}>
                  {micWorking
                    ? 'Microphone working — your voice registers clearly.'
                    : micStatus === 'active'
                      ? 'Listening… say a sentence to test your microphone.'
                      : 'Connecting to your microphone…'}
                </p>

                <button
                  onClick={() => setStep('participants')}
                  disabled={!micWorking}
                  className="px-6 py-3 bg-gray-900 hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-xl text-sm font-medium shadow-md hover:shadow-lg disabled:shadow-none transition-all duration-200 active:scale-[0.98]"
                >
                  Continue to Voice Registration
                </button>
              </>
            )}
          </div>
        )}

        {/* ---- 4. Who's in this meeting? ---- */}
        {step === 'participants' && (
          <div className="animate-fade-up">
            <h1 className="text-2xl font-bold text-gray-900 text-center mb-3">
              Who&apos;s in this meeting?
            </h1>
            <p className="text-sm text-gray-500 text-center mb-8 max-w-md mx-auto">
              Donna listens better when it knows who&apos;s speaking. Add each
              participant and say one sentence so we can confirm their voice registers.
            </p>

            <div className="border border-gray-200 rounded-2xl p-6 mb-4">
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Name</label>
              <input
                value={nameInput}
                onChange={(e) => { setNameInput(e.target.value); setRecordError(null); }}
                placeholder="e.g. Alex"
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow mb-4"
              />

              <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                Expertise areas <span className="font-normal text-gray-400">(optional, comma-separated)</span>
              </label>
              <input
                value={expertiseInput}
                onChange={(e) => setExpertiseInput(e.target.value)}
                placeholder="e.g. pricing strategy, supply chain, cushioning systems"
                className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow mb-1"
              />
              <p className="text-[11px] text-gray-400 mb-4">
                Donna surfaces a &ldquo;your expertise needed&rdquo; card when the conversation enters their lane.
              </p>

              <p className="text-xs font-semibold text-gray-700 mb-1.5">Voice Prompt</p>
              {!nameInput.trim() ? (
                <p className="text-[13px] text-gray-400 mb-2">Please enter your name first</p>
              ) : (
                <p className="text-[13px] text-gray-500 mb-2">
                  Press record and say: &ldquo;Hi, I&apos;m {nameInput.trim()}, joining the {meeting.title || 'meeting'}.&rdquo;
                </p>
              )}

              <div className="flex items-center gap-3">
                <button
                  onClick={recordVoiceCheck}
                  disabled={!nameInput.trim() || recording}
                  className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                    recording
                      ? 'bg-red-50 text-red-600 border border-red-200'
                      : 'bg-gray-900 hover:bg-gray-800 disabled:bg-gray-100 disabled:text-gray-400 text-white'
                  }`}
                >
                  {recording ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                      Recording… speak now
                    </>
                  ) : (
                    <>
                      <Mic className="w-3.5 h-3.5" />
                      Record voice check
                    </>
                  )}
                </button>
                {recording && (
                  <div className="flex items-end gap-0.5 h-5">
                    {Array.from({ length: 10 }, (_, i) => (
                      <span
                        key={i}
                        className={`w-1 rounded-full transition-all duration-75 ${
                          level > (i / 10) * 100 ? 'bg-red-400' : 'bg-gray-200'
                        }`}
                        style={{ height: `${6 + (i % 4) * 4}px` }}
                      />
                    ))}
                  </div>
                )}
              </div>

              {recordError && (
                <p className="text-xs text-amber-600 mt-2.5">{recordError}</p>
              )}
              {nameInput.trim() && !recording && (
                <button
                  onClick={addWithoutCheck}
                  className="text-[11px] text-gray-400 hover:text-gray-600 underline mt-3 transition-colors"
                >
                  Add without voice check (remote participant)
                </button>
              )}
            </div>

            {/* Registered participants */}
            {participants.length > 0 && (
              <div className="space-y-2 mb-4">
                {participants.map((p) => (
                  <div
                    key={p.name}
                    className="flex items-center justify-between px-4 py-2.5 bg-gray-50 rounded-xl"
                  >
                    <div className="flex items-center gap-2.5 flex-wrap">
                      {p.registered ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <Users className="w-4 h-4 text-gray-400" />
                      )}
                      <span className="text-sm font-medium text-gray-900">{p.name}</span>
                      {p.registered && (
                        <span className="text-[10px] text-emerald-600 font-medium">Voice checked</span>
                      )}
                      {p.expertise.map((ex) => (
                        <span key={ex} className="px-1.5 py-0.5 bg-teal-50 text-teal-600 border border-teal-100 rounded text-[10px]">
                          {ex}
                        </span>
                      ))}
                    </div>
                    <button
                      onClick={() => setParticipants((prev) => prev.filter((x) => x.name !== p.name))}
                      className="p-1 text-gray-300 hover:text-red-500 rounded transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <button
              onClick={() => document.querySelector<HTMLInputElement>('input[placeholder="e.g. Alex"]')?.focus()}
              className="w-full flex items-center justify-center gap-1.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors mb-4"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Another
            </button>

            <button
              onClick={completeRegistration}
              disabled={participants.length === 0 || saving}
              className="w-full flex items-center justify-center gap-2 py-3 bg-gray-900 hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-xl text-sm font-medium shadow-md hover:shadow-lg disabled:shadow-none transition-all duration-200"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Complete Registration
            </button>
            <p className="text-[11px] text-gray-400 text-center mt-3">
              Donna uses these names to attribute each speaker in the transcript and summary.
            </p>
          </div>
        )}

        {/* ---- 5. All set! ---- */}
        {step === 'done' && (
          <div className="text-center animate-fade-up">
            <div className="w-20 h-20 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-6">
              <Check className="w-10 h-10 text-emerald-500" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900 mb-2">All set!</h1>
            <p className="text-sm text-gray-500 mb-8">
              Microphone working and {participants.length}{' '}
              {participants.length === 1 ? 'participant' : 'participants'} registered.
              <br />
              Ready to start your Donna meeting.
            </p>

            <div className="flex items-start gap-3 p-4 bg-gray-50 rounded-xl text-left mb-8">
              <Mic className="w-4 h-4 text-gray-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-gray-900">Speaker attribution active</p>
                <p className="text-[13px] text-gray-500 mt-0.5">
                  Donna will attribute the live transcript to your registered
                  participants throughout the meeting.
                </p>
              </div>
            </div>

            <button
              onClick={finish}
              className="w-full flex items-center justify-center gap-2 py-3.5 bg-gray-900 hover:bg-gray-800 text-white rounded-xl text-sm font-semibold shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
            >
              <Check className="w-4 h-4" />
              Start Meeting with Donna
            </button>
            <p className="text-[11px] text-gray-400 mt-3">
              When you start the meeting, Donna will begin listening and analyzing your conversation.
            </p>

            {/* Completion toast (PDF bottom-right) */}
            <div className="fixed bottom-6 right-6 bg-white border border-gray-200 rounded-xl shadow-elevated px-4 py-3 text-left animate-slide-in">
              <p className="text-sm font-semibold text-gray-900">Voice registration complete</p>
              <p className="text-xs text-gray-500 mt-0.5">All participants have been registered successfully.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
