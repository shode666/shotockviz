interface ErrorStateProps {
    title?: string;
    message: string;
    onRetry?: () => void;
    isLoading?: boolean;
    icon?: string;
}

export function ErrorState({
    title = 'เกิดข้อผิดพลาด',
    message,
    onRetry,
    isLoading = false,
    icon = '⚠',
}: ErrorStateProps) {
    return (
        <div
            className="flex-1 overflow-auto p-5 flex items-center justify-center"
            style={{ background: 'var(--color-bg)' }}
        >
            <div
                className="max-w-md mx-auto panel border rounded-2xl p-8 text-center"
                style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
            >
                <div className="text-4xl mb-4">{icon}</div>
                <h3 className="text-sm font-semibold mb-2">{title}</h3>
                <p className="text-xs mb-6" style={{ color: 'var(--color-text-sub)' }}>
                    {message}
                </p>
                {onRetry && (
                    <button onClick={onRetry} disabled={isLoading} className="btn-accent px-6 py-2 text-xs">
                        {isLoading ? 'กำลังลองใหม่…' : 'ลองใหม่'}
                    </button>
                )}
            </div>
        </div>
    );
}
