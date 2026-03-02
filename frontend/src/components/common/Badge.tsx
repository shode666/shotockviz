import React from 'react';

type BadgeVariant = 'positive' | 'negative' | 'neutral' | 'warning' | 'info';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  positive: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  negative: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  neutral: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  warning: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  info: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
};

const sizeClasses = {
  sm: 'text-[10px] px-1.5 py-0.5',
  md: 'text-xs px-2 py-1',
};

export function Badge({ children, variant = 'neutral', size = 'md', className = '' }: BadgeProps) {
  return (
    <span className={`
      inline-flex items-center gap-1 rounded-full border font-medium
      ${variantClasses[variant]}
      ${sizeClasses[size]}
      ${className}
    `}>
      {children}
    </span>
  );
}

// Convenience components
export function ChangeBadge({ value, className = '' }: { value: number; className?: string }) {
  const variant = value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';
  const sign = value > 0 ? '+' : '';
  return (
    <Badge variant={variant} className={className}>
      {sign}{value.toFixed(2)}%
    </Badge>
  );
}

export function MarketStatusBadge({ isOpen }: { isOpen: boolean }) {
  return (
    <Badge variant={isOpen ? 'positive' : 'neutral'} size="sm">
      <span className={`w-1.5 h-1.5 rounded-full ${isOpen ? 'bg-emerald-400 animate-pulse' : 'bg-slate-400'}`} />
      {isOpen ? 'Open' : 'Closed'}
    </Badge>
  );
}
