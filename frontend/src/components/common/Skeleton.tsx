import React from 'react';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'rect' | 'circle';
  width?: string | number;
  height?: string | number;
  lines?: number; // for text variant, number of lines
}

export function Skeleton({ className = '', variant = 'rect', width, height, lines = 1 }: SkeletonProps) {
  const base = 'animate-pulse rounded bg-slate-700/50 relative overflow-hidden';
  const shimmer = `after:absolute after:inset-0 after:bg-gradient-to-r after:from-transparent after:via-slate-600/20 after:to-transparent after:animate-[shimmer_1.5s_infinite]`;

  if (variant === 'text') {
    return (
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={`${base} ${shimmer} h-4 ${i === lines - 1 && lines > 1 ? 'w-3/4' : 'w-full'} ${className}`}
            style={{ width, height }}
          />
        ))}
      </div>
    );
  }

  if (variant === 'circle') {
    return (
      <div
        className={`${base} ${shimmer} rounded-full ${className}`}
        style={{ width: width || '40px', height: height || '40px' }}
      />
    );
  }

  return (
    <div
      className={`${base} ${shimmer} ${className}`}
      style={{ width, height }}
    />
  );
}

// Pre-built skeleton layouts for common use cases
export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`p-4 rounded-xl border border-slate-700/50 bg-slate-800/50 space-y-3 ${className}`}>
      <Skeleton height="16px" width="60%" />
      <Skeleton height="32px" width="80%" />
      <Skeleton height="12px" lines={2} />
    </div>
  );
}

export function SkeletonChart({ className = '' }: { className?: string }) {
  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      <Skeleton height="100%" className="flex-1 min-h-[400px] rounded-xl" />
    </div>
  );
}

export function SkeletonSidebarItem() {
  return (
    <div className="flex items-center justify-between px-3 py-2">
      <div className="space-y-1.5 flex-1">
        <Skeleton height="14px" width="50px" />
        <Skeleton height="11px" width="80px" />
      </div>
      <div className="text-right space-y-1.5">
        <Skeleton height="14px" width="60px" />
        <Skeleton height="11px" width="40px" />
      </div>
    </div>
  );
}
