'use client';

import React, { useEffect, useState } from 'react';
import { FileText, Zap, TrendingUp, Clock, Activity } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { UsageAnalytics, PerformanceAnalytics } from '@/types';
import { formatLatency } from '@/lib/utils';

export default function AnalyticsDashboard() {
  const [usage, setUsage] = useState<UsageAnalytics | null>(null);
  const [performance, setPerformance] = useState<PerformanceAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const [usageData, perfData] = await Promise.all([
          apiClient.getUsageAnalytics(),
          apiClient.getPerformanceAnalytics(),
        ]);

        setUsage(usageData);
        setPerformance(perfData);
      } catch (error) {
        console.error('Failed to fetch analytics:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();

    // Refresh every 30 seconds
    const interval = setInterval(fetchAnalytics, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const successRate = usage?.documents
    ? (usage.documents.completed / usage.documents.total * 100) || 0
    : 0;

  if (!usage || !performance) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        No analytics data available yet
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Documents */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Total Documents</p>
              <p className="text-3xl font-bold text-gray-900 mt-1">
                {usage?.documents.total || 0}
              </p>
            </div>
            <div className="p-3 bg-blue-100 rounded-lg">
              <FileText className="w-6 h-6 text-blue-600" />
            </div>
          </div>

          <div className="mt-4 flex items-center gap-2 text-sm">
            <span className="text-green-600 font-medium">
              {usage?.documents.completed || 0} completed
            </span>
            <span className="text-gray-400">•</span>
            <span className="text-yellow-600">
              {usage?.documents.processing || 0} processing
            </span>
          </div>
        </div>

        {/* Total Chunks */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Total Chunks</p>
              <p className="text-3xl font-bold text-gray-900 mt-1">
                {usage?.chunks.total.toLocaleString() || 0}
              </p>
            </div>
            <div className="p-3 bg-purple-100 rounded-lg">
              <Zap className="w-6 h-6 text-purple-600" />
            </div>
          </div>

          <div className="mt-4 text-sm text-gray-600">
            Avg: {usage?.chunks.average_per_doc.toFixed(1) || 0} per document
          </div>
        </div>

        {/* Success Rate */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Success Rate</p>
              <p className="text-3xl font-bold text-gray-900 mt-1">
                {successRate.toFixed(0)}%
              </p>
            </div>
            <div className="p-3 bg-green-100 rounded-lg">
              <TrendingUp className="w-6 h-6 text-green-600" />
            </div>
          </div>

          <div className="mt-4 w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-green-600 h-2 rounded-full transition-all duration-500"
              style={{ width: `${successRate}%` }}
            />
          </div>
        </div>

        {/* Active Sessions */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Active Sessions</p>
              <p className="text-3xl font-bold text-gray-900 mt-1">
                {performance?.active_sessions || 0}
              </p>
            </div>
            <div className="p-3 bg-orange-100 rounded-lg">
              <Activity className="w-6 h-6 text-orange-600" />
            </div>
          </div>

          <div className="mt-4 text-sm text-gray-600">
            Voice conversations
          </div>
        </div>
      </div>

      {/* Performance Metrics */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center gap-2 mb-6">
          <Clock className="w-5 h-5 text-gray-600" />
          <h3 className="text-lg font-semibold text-gray-900">
            Average Latencies
          </h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <div>
            <p className="text-xs text-gray-600 mb-1">Speech-to-Text</p>
            <p className="text-2xl font-bold text-blue-600">
              {formatLatency(performance?.average_latencies.stt || 0)}
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-blue-600 h-1.5 rounded-full"
                style={{ width: `${Math.min((performance?.average_latencies.stt || 0) / 5, 100)}%` }}
              />
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-600 mb-1">LLM Processing</p>
            <p className="text-2xl font-bold text-purple-600">
              {formatLatency(performance?.average_latencies.llm || 0)}
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-purple-600 h-1.5 rounded-full"
                style={{ width: `${Math.min((performance?.average_latencies.llm || 0) / 20, 100)}%` }}
              />
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-600 mb-1">Text-to-Speech</p>
            <p className="text-2xl font-bold text-green-600">
              {formatLatency(performance?.average_latencies.tts || 0)}
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-green-600 h-1.5 rounded-full"
                style={{ width: `${Math.min((performance?.average_latencies.tts || 0) / 2, 100)}%` }}
              />
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-600 mb-1">RAG Retrieval</p>
            <p className="text-2xl font-bold text-orange-600">
              {formatLatency(performance?.average_latencies.rag || 0)}
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-orange-600 h-1.5 rounded-full"
                style={{ width: `${Math.min((performance?.average_latencies.rag || 0) / 5, 100)}%` }}
              />
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-600 mb-1">Total Pipeline</p>
            <p className="text-2xl font-bold text-gray-900">
              {formatLatency(performance?.average_latencies.total || 0)}
            </p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-gray-900 h-1.5 rounded-full"
                style={{ width: `${Math.min((performance?.average_latencies.total || 0) / 30, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Processing Methods */}
      {usage && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Processing Methods
          </h3>

          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-primary-50 rounded-lg">
              <p className="text-sm text-gray-600 mb-1">Enhanced Contextual</p>
              <p className="text-3xl font-bold text-primary-600">
                {usage?.processing_methods?.enhanced_contextual ?? 0}
              </p>
              <p className="text-xs text-gray-500 mt-2">
                3-level embeddings with full context
              </p>
            </div>

            <div className="p-4 bg-gray-100 rounded-lg">
              <p className="text-sm text-gray-600 mb-1">Basic Processing</p>
              <p className="text-3xl font-bold text-gray-700">
                {usage?.processing_methods?.basic ?? 0}
              </p>
              <p className="text-xs text-gray-500 mt-2">
                Standard document processing
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
