'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Navbar } from '../../components/navbar';
import { CardSkeleton } from '../../components/shared/CardSkeleton';
import { EmptyState } from '../../components/shared/EmptyState';
import { KnowledgeDTO } from '../../lib/types';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { tx } from '../../lib/typography';
import {
  BookOpen,
  Plus,
  Search,
  RefreshCw,
  Tag,
  Server,
  Clock,
  FileText,
  X,
  Link2,
  Sparkles,
} from 'lucide-react';

/* Fallback demo knowledge entries */
const DEMO_ENTRIES: KnowledgeDTO[] = [
  {
    id: 'kb-001',
    title: 'Postgres Connection Pool Exhaustion Runbook',
    content: `When the connection pool is exhausted, all incoming DB requests will queue or fail.

## Remediation Steps
1. Run SELECT count(*) FROM pg_stat_activity; to check active connections
2. Identify long-running idle connections
3. Terminate idle connections if query_start < NOW() - INTERVAL '5 minutes'
4. Increase max_connections in postgresql.conf if necessary and reload`,
    service: 'db-cluster',
    tags: ['postgres', 'connections', 'critical', 'database'],
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
  },
  {
    id: 'kb-002',
    title: 'Auth Service JWT Token Cache Miss Storm',
    content: `A cache miss storm occurs when the Redis JWT validation cache is evicted en masse.

## Remediation Steps
1. Increase Redis maxmemory via CONFIG SET
2. Set maxmemory-policy allkeys-lru
3. Warm cache with synthetic requests`,
    service: 'auth-service',
    tags: ['redis', 'jwt', 'cache', 'auth'],
    created_at: new Date(Date.now() - 7 * 86400000).toISOString(),
  },
  {
    id: 'kb-003',
    title: 'Kubernetes Pod OOMKilled Recovery',
    content: `Pod restart loop due to exit code 137 (OOMKilled).

## Steps
1. Check limits: kubectl describe pod <name>
2. Increase memory limit in deployment spec
3. Apply: kubectl rollout restart deployment/<name>`,
    service: 'api-gateway',
    tags: ['kubernetes', 'oom', 'memory', 'pods'],
    created_at: new Date(Date.now() - 14 * 86400000).toISOString(),
  },
];

export default function KnowledgePage() {
  const { session, hasRole } = useAuth();
  const [entries, setEntries] = useState<KnowledgeDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  // Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [newTagsStr, setNewTagsStr] = useState('');
  const [newService, setNewService] = useState('auth-service');
  const [creating, setCreating] = useState(false);

  const canAdd = hasRole('engineer');

  const fetchKnowledge = async () => {
    if (!session?.token) return;
    setLoading(true);

    try {
      const data = await apiClient.searchKnowledge(session.token, {
        q: searchQuery.trim() || undefined,
        tags: selectedTag || undefined,
      });
      setEntries(data || DEMO_ENTRIES);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load runbooks');
      setEntries(DEMO_ENTRIES);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchKnowledge();
    }, 300);
    return () => clearTimeout(timer);
  }, [session, searchQuery, selectedTag]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.token || !newTitle.trim()) return;

    setCreating(true);
    try {
      const tagsArray = newTagsStr.split(',').map((t) => t.trim()).filter(Boolean);
      await apiClient.createKnowledge(session.token, {
        title: newTitle,
        content: newContent,
        tags: tagsArray,
        service: newService,
      });
      setShowCreateModal(false);
      setNewTitle('');
      setNewContent('');
      setNewTagsStr('');
      fetchKnowledge();
    } catch (err: any) {
      alert(`Failed to save runbook: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  // Collect unique tags
  const allTags = Array.from(new Set(entries.flatMap((e) => e.tags || [])));

  return (
    <div className="min-h-screen bg-[#FAF7F2] text-[#0E0B14]">
      {/* Shell Navbar remains dark */}
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className={tx('sectionHeadline', 'text-[#0E0B14] flex items-center gap-3')}>
              <BookOpen className="w-8 h-8 text-[#4C2A85]" />
              <span>Incident Knowledge & Runbooks</span>
            </h1>
            <p className={tx('sectionSubhead', 'text-[#5A5550] mt-1')}>
              Curated runbooks, historical resolution steps, and semantic search vector repository
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchKnowledge}
              className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9] bg-white px-4 py-2 text-xs font-semibold text-[#0E0B14] hover:bg-[#E8E2D9]/20 transition-colors shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>

            {canAdd && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 rounded-lg bg-[#4C2A85] px-4 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6] transition-colors shadow-md"
              >
                <Plus className="w-4 h-4" />
                <span>Add Runbook</span>
              </button>
            )}
          </div>
        </div>

        {/* Search & Tag Filter Bar */}
        <div className="space-y-4">
          <div className="relative max-w-2xl">
            <Search className="pointer-events-none absolute left-4 top-3.5 h-4 w-4 text-[#6B6560]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search runbooks, incident patterns, vector query..."
              className={tx(
                'inputText',
                'w-full rounded-xl border border-[#E8E2D9] bg-white pl-11 pr-4 py-3 text-[#0E0B14] placeholder-[#6B6560]/60 shadow-sm focus:border-[#8B5CF6] focus:outline-none focus:ring-2 focus:ring-[#8B5CF6]/20 transition-all'
              )}
            />
          </div>

          {/* Tag Filter Chips (Blast Radius Pill Visual Style) */}
          {allTags.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className={tx('cardMeta', 'text-[#5A5550]')}>Filter Tags:</span>
              <button
                onClick={() => setSelectedTag(null)}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-all ${
                  selectedTag === null
                    ? 'bg-[#4C2A85] text-[#FAF7F2]'
                    : 'bg-[#4C2A85]/10 text-[#4C2A85] border border-[#4C2A85]/30 hover:bg-[#4C2A85]/20'
                }`}
              >
                All
              </button>
              {allTags.map((tag) => (
                <button
                  key={tag}
                  onClick={() => setSelectedTag(selectedTag === tag ? null : tag)}
                  className={`px-3 py-1 rounded-full text-xs font-semibold transition-all ${
                    selectedTag === tag
                      ? 'bg-[#4C2A85] text-[#FAF7F2]'
                      : 'bg-[#4C2A85]/10 text-[#4C2A85] border border-[#4C2A85]/30 hover:bg-[#4C2A85]/20'
                  }`}
                >
                  #{tag}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Content Grid */}
        {loading ? (
          <CardSkeleton count={3} variant="knowledge" theme="light" />
        ) : entries.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title="No knowledge entries match your search"
            description="Try adjusting your search query or removing tag filters."
            action={
              searchQuery || selectedTag
                ? {
                    label: 'Clear Search',
                    onClick: () => {
                      setSearchQuery('');
                      setSelectedTag(null);
                    },
                  }
                : undefined
            }
            theme="light"
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {entries.map((entry) => (
              <div
                key={entry.id}
                data-testid="knowledge-card"
                className="rounded-xl border border-[#E8E2D9] bg-white p-6 shadow-sm hover:border-[#8B5CF6] hover:shadow-md transition-all duration-200 flex flex-col justify-between space-y-4"
              >
                <div className="space-y-3">
                  {/* Title uses Fraunces (reading-focused departure) */}
                  <h3 className={tx('sectionSubhead', 'text-[#0E0B14] font-serif font-semibold')}>
                    {entry.title}
                  </h3>

                  {/* Preview */}
                  <p className={tx('bodyProse', 'text-[#5A5550] text-sm line-clamp-3')}>
                    {entry.content}
                  </p>
                </div>

                <div className="space-y-3 pt-3 border-t border-[#E8E2D9]">
                  {/* Tag Chips — verified WCAG 8.93:1 contrast */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {entry.tags?.map((tag, i) => (
                      <span
                        key={i}
                        className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#EDEAF3] text-[#4C2A85] border border-[#4C2A85]/20"
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>

                  {/* Metadata */}
                  <div className="flex items-center justify-between text-xs text-[#6B6560] font-mono">
                    <span>{entry.service || 'global'}</span>
                    <span className="tabular-nums">
                      {new Date(entry.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Add Runbook Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 text-[#0E0B14]">
            <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-[#E8E2D9] bg-white p-6 shadow-2xl space-y-6">
              <div className="flex items-center justify-between border-b border-[#E8E2D9] pb-4">
                <h3 className={tx('sectionHeader', 'text-[#0E0B14] normal-case text-lg font-semibold')}>
                  Curate New Knowledge Base Runbook
                </h3>
                <button onClick={() => setShowCreateModal(false)} className="text-[#6B6560] hover:text-[#0E0B14]">
                  <X className="h-5 w-5" />
                </button>
              </div>

              <form onSubmit={handleCreateSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Runbook Title</label>
                  <input
                    type="text"
                    required
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Redis Cluster OOM Mitigation"
                    className="w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] px-3.5 py-2 text-sm text-[#0E0B14] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Target Service</label>
                  <input
                    type="text"
                    required
                    value={newService}
                    onChange={(e) => setNewService(e.target.value)}
                    placeholder="e.g. auth-service"
                    className="w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] px-3.5 py-2 text-sm text-[#0E0B14] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Tags (Comma-separated)</label>
                  <input
                    type="text"
                    value={newTagsStr}
                    onChange={(e) => setNewTagsStr(e.target.value)}
                    placeholder="e.g. redis, oom, memory"
                    className="w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] px-3.5 py-2 text-xs font-mono text-[#0E0B14] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Runbook Content (Markdown)</label>
                  <textarea
                    required
                    rows={6}
                    value={newContent}
                    onChange={(e) => setNewContent(e.target.value)}
                    placeholder="Provide detailed diagnostic steps, commands, and rollback instructions..."
                    className="w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] px-3.5 py-2 text-xs font-mono text-[#0E0B14] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]">
                  <button
                    type="button"
                    onClick={() => setShowCreateModal(false)}
                    className="rounded-lg border border-[#E8E2D9] px-4 py-2 text-xs font-semibold text-[#0E0B14] hover:bg-[#FAF7F2]"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creating}
                    className="rounded-lg bg-[#4C2A85] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6] disabled:opacity-50"
                  >
                    {creating ? 'Saving Runbook...' : 'Save Runbook'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
