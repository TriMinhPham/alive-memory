"use client";

import { useState, useEffect, useCallback } from "react";
import type { CapabilityWithUsage, ChannelStatus } from "@/lib/types";

interface TeachTabProps {
  agentId: string;
  status: "connected" | "reconnecting" | "offline" | "error";
}

function Skeleton({ className }: { className?: string }) {
  return <div className={`bg-[#1e1e1a] rounded animate-skeleton ${className ?? ""}`} />;
}

export default function TeachTab({ agentId, status }: TeachTabProps) {
  const isOffline = status === "offline" || status === "error";

  return (
    <div className="space-y-6">
      <CapabilitySection agentId={agentId} isOffline={isOffline} />
      <ChannelSection agentId={agentId} />
      {/* MCP placeholder — subtle */}
      <div className="p-3 border border-[#1e1e1a]/50 rounded-lg">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xs font-medium text-[#525252]">MCP Tools</h3>
            <p className="text-[10px] text-[#3a3a3a] mt-0.5">
              Connect external tools
            </p>
          </div>
          <span className="text-[10px] text-[#3a3a3a]">Coming soon</span>
        </div>
      </div>
    </div>
  );
}

/* ── Capability Section ── */

function CapabilitySection({
  agentId,
  isOffline,
}: {
  agentId: string;
  isOffline: boolean;
}) {
  const [capabilities, setCapabilities] = useState<CapabilityWithUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);

  const fetchCapabilities = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/capabilities`);
      if (res.ok) {
        const data = await res.json();
        setCapabilities(
          Array.isArray(data)
            ? data
            : data.capabilities || data.actions || []
        );
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchCapabilities();
  }, [fetchCapabilities]);

  async function handleToggle(action: string, enabled: boolean) {
    setToggling(action);
    try {
      const res = await fetch(`/api/agents/${agentId}/capabilities`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, enabled: !enabled }),
      });
      if (res.ok) {
        await fetchCapabilities();
      }
    } catch {
      // silent
    } finally {
      setToggling(null);
    }
  }

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-[#9a8c7a] uppercase tracking-wider">
        Capabilities
      </h3>

      {loading ? (
        <div className="space-y-1.5">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="flex items-center justify-between p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg">
              <div className="flex-1">
                <Skeleton className="h-3 w-24 mb-1" />
                <Skeleton className="h-2 w-32" />
              </div>
              <Skeleton className="h-5 w-9 rounded-full" />
            </div>
          ))}
        </div>
      ) : capabilities.length === 0 ? (
        <p className="text-xs text-[#525252] italic">
          No capabilities available
        </p>
      ) : (
        <div className="space-y-1.5">
          {capabilities.map((cap) => (
            <div
              key={cap.name}
              className="flex items-center justify-between p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
            >
              <div className="flex-1 min-w-0 mr-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[#d4d4d4]">
                    {formatCapName(cap.name)}
                  </span>
                  {cap.usage_count !== undefined && cap.usage_count > 0 && (
                    <span className="text-[10px] text-[#525252]">
                      &times;{cap.usage_count}
                    </span>
                  )}
                </div>
                {cap.description && (
                  <p className="text-[10px] text-[#525252] mt-0.5 truncate">
                    {cap.description}
                  </p>
                )}
              </div>
              <button
                onClick={() => handleToggle(cap.name, cap.enabled)}
                disabled={isOffline || toggling === cap.name}
                className={`relative w-9 h-5 rounded-full transition-colors ${
                  cap.enabled ? "bg-[#d4a574]" : "bg-[#262620]"
                } disabled:opacity-40`}
              >
                <span
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    cap.enabled ? "left-[18px]" : "left-0.5"
                  }`}
                />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatCapName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ── Channel Section ── */

function ChannelSection({ agentId }: { agentId: string }) {
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchChannels = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/channels`);
      if (res.ok) {
        const data = await res.json();
        setChannels(data.channels || []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels]);

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium text-[#9a8c7a] uppercase tracking-wider">
        Channels
      </h3>

      {loading ? (
        <div className="space-y-1.5">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg">
              <Skeleton className="h-3 w-20" />
            </div>
          ))}
        </div>
      ) : channels.length === 0 ? (
        <p className="text-xs text-[#525252] italic">No channels configured</p>
      ) : (
        <div className="space-y-1.5">
          {channels.map((ch) => (
            <div
              key={ch.channel}
              className="flex items-center justify-between p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    ch.enabled ? "bg-emerald-500" : "bg-[#525252]"
                  }`}
                />
                <span className="text-xs text-[#d4d4d4] capitalize">
                  {ch.channel}
                </span>
              </div>
              {ch.message_count !== undefined && (
                <span className="text-[10px] text-[#525252]">
                  {ch.message_count}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
