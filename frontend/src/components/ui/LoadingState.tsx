import { SkeletonCard, Skeleton } from '@/components/common/Skeleton';

interface LoadingStateProps {
    variant?: 'card' | 'table' | 'dashboard';
}

export function LoadingState({ variant = 'card' }: LoadingStateProps) {
    if (variant === 'table') {
        return (
            <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                    {[1, 2, 3, 4].map((i) => (
                        <div
                            key={i}
                            className="panel border rounded-2xl p-4 h-24 animate-pulse"
                            style={{
                                borderWidth: 1,
                                borderStyle: 'solid',
                                borderColor: 'var(--color-border)',
                            }}
                        />
                    ))}
                </div>
                <div
                    className="panel border rounded-2xl overflow-hidden animate-pulse"
                    style={{
                        borderWidth: 1,
                        borderStyle: 'solid',
                        borderColor: 'var(--color-border)',
                    }}
                >
                    <div
                        className="px-4 py-3 border-b h-10"
                        style={{ borderColor: 'var(--color-border)', background: 'var(--color-hover)' }}
                    />
                    <div className="p-4 space-y-3">
                        {[1, 2, 3, 4].map((i) => (
                            <div
                                key={i}
                                className="h-8 rounded"
                                style={{ background: 'var(--color-hover)' }}
                            />
                        ))}
                    </div>
                </div>
            </>
        );
    }

    if (variant === 'dashboard') {
        return (
            <div className="flex-1 overflow-auto p-5" style={{ background: 'var(--color-bg)' }}>
                <div className="max-w-7xl mx-auto space-y-4">
                    <Skeleton height="28px" width="25%" />
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
                        {[...Array(5)].map((_, i) => (
                            <Skeleton key={i} height="72px" className="rounded-xl" />
                        ))}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
                        <SkeletonCard className="md:col-span-2" />
                        <SkeletonCard />
                        <SkeletonCard className="md:col-span-3 xl:col-span-4" />
                        <SkeletonCard className="md:col-span-3 xl:col-span-4" />
                    </div>
                </div>
            </div>
        );
    }

    // Default card skeleton
    return (
        <div
            className="panel border rounded-2xl p-8 animate-pulse"
            style={{
                borderWidth: 1,
                borderStyle: 'solid',
                borderColor: 'var(--color-border)',
            }}
        >
            <div className="h-6 rounded mb-4" style={{ background: 'var(--color-hover)' }} />
            <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                    <div
                        key={i}
                        className="h-4 rounded"
                        style={{ background: 'var(--color-hover)' }}
                    />
                ))}
            </div>
        </div>
    );
}
