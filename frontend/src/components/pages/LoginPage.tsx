/**
 * LoginPage — Google OAuth entry point.
 *
 * SSR / Hydration fix:
 *  GoogleOAuthProvider + GoogleLogin are wrapped in <ClientOnly> so they never
 *  render on the server.  The Google OAuth SDK injects its own DOM which differs
 *  from what React expects, causing hydration mismatches if rendered on the server.
 *  ClientOnly defers the subtree to the first client-side paint, sidestepping
 *  the mismatch entirely.
 *
 * Token missing fix:
 *  authStore now exposes `token` in its Zustand state (synced with localStorage)
 *  so useWebSocket can subscribe reactively.
 */
import { useState } from 'react'
import { GoogleLogin, GoogleOAuthProvider } from '@react-oauth/google'
import { useNavigate } from '@tanstack/react-router'
import ShotockLogo from '@/components/common/ShotockLogo'
import ClientOnly from '@/components/common/ClientOnly'
import useAuthStore from '@/store/authStore'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined

export default function LoginPage() {
    const { googleLogin } = useAuthStore()
    const navigate = useNavigate()
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    const handleGoogleSuccess = async (credentialResponse: any) => {
        setError('')
        setLoading(true)
        try {
            await googleLogin(credentialResponse.credential)
            navigate({ to: '/' })
        } catch (err: any) {
            const msg = err?.response?.data?.detail
                ?? err?.message
                ?? 'Google login failed — please try again'
            setError(msg)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="flex-1 flex items-center justify-center p-8" style={{ background: 'var(--color-bg)' }}>
            <div className="glass-panel rounded-3xl w-full max-w-sm animate-slide-up overflow-hidden">

                {/* ── Gradient header ───────────────────────────────────── */}
                <div
                    className="px-10 pt-12 pb-10 text-center"
                    style={{ background: 'linear-gradient(135deg, rgba(124,92,252,0.10), rgba(168,85,247,0.06))' }}
                >
                    <div className="flex items-center gap-4 justify-center mb-6">
                        <ShotockLogo className="w-[60px] h-[60px] rounded-[18px] shadow-[0_8px_24px_rgba(168,85,247,0.3)]" />
                        <div className="text-4xl tracking-tight flex items-baseline select-none">
                            <span className="font-extrabold tracking-tight text-gray-900 dark:text-white">S</span>
                            <span
                                className="font-semibold tracking-[-.15em] text-orange-500 dark:text-violet-300 w-2 -translate-x-2 text-xl"
                                style={{ textShadow: 'var(--ho-glow, none)' }}
                            >ho</span>
                            <span className="font-extrabold tracking-tight text-gray-900 dark:text-white">tock</span>
                            <span className="font-semibold text-orange-500 dark:text-violet-300 ml-1"
                                style={{ textShadow: 'var(--ho-glow, none)' }}
                            >Viz</span>
                        </div>
                    </div>
                    <h2 className="text-base font-semibold mb-2">Stock Analysis Platform</h2>
                    <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-sub)' }}>
                        แพลตฟอร์มวิเคราะห์หุ้นไทยและสหรัฐ<br />
                        Self-hosted · ฟรี · ไม่มีค่าบริการรายเดือน
                    </p>
                </div>

                {/* ── Body ─────────────────────────────────────────────── */}
                <div className="px-10 py-10">

                    {/* Error */}
                    {error && (
                        <div
                            className="text-xs mb-6 w-full text-center py-3 px-4 rounded-2xl font-medium"
                            style={{ background: 'rgba(248,113,113,0.10)', color: 'var(--color-red)' }}
                        >
                            {error}
                        </div>
                    )}

                    {/* Google Sign-In — deferred to client to avoid SSR hydration mismatch */}
                    <div className="flex flex-col items-center gap-4 mb-6">
                        <ClientOnly
                            fallback={
                                /* Same size as the real button so layout doesn't jump */
                                <div
                                    className="flex items-center justify-center gap-2 rounded-full"
                                    style={{
                                        width: 300, height: 44,
                                        background: 'var(--color-hover)',
                                        border: '1px solid var(--color-border)',
                                    }}
                                >
                                    <span
                                        style={{
                                            display: 'inline-block',
                                            width: 14, height: 14,
                                            border: '2px solid var(--color-border)',
                                            borderTopColor: 'var(--color-accent)',
                                            borderRadius: '50%',
                                            animation: 'spin 0.65s linear infinite',
                                        }}
                                    />
                                    <span className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                        กำลังโหลด...
                                    </span>
                                </div>
                            }
                        >
                            {!GOOGLE_CLIENT_ID ? (
                                <div
                                    className="text-xs text-center py-3 px-4 rounded-2xl w-full"
                                    style={{ background: 'rgba(248,113,113,0.08)', color: 'var(--color-red)' }}
                                >
                                    <strong>VITE_GOOGLE_CLIENT_ID</strong> ไม่ได้ตั้งค่า<br />
                                    <span style={{ opacity: 0.7 }}>เพิ่มใน .env แล้ว restart</span>
                                </div>
                            ) : loading ? (
                                <div
                                    className="flex items-center justify-center gap-2 rounded-full text-xs"
                                    style={{
                                        width: 300, height: 44,
                                        background: 'var(--color-hover)',
                                        border: '1px solid var(--color-border)',
                                        color: 'var(--color-text-sub)',
                                    }}
                                >
                                    <span
                                        style={{
                                            display: 'inline-block',
                                            width: 14, height: 14,
                                            border: '2px solid var(--color-border)',
                                            borderTopColor: 'var(--color-accent)',
                                            borderRadius: '50%',
                                            animation: 'spin 0.65s linear infinite',
                                        }}
                                    />
                                    กำลังเข้าสู่ระบบ...
                                </div>
                            ) : (
                                <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
                                    <GoogleLogin
                                        onSuccess={handleGoogleSuccess}
                                        onError={() => setError('Google login failed — check popup blocker and try again')}
                                        theme="filled_black"
                                        size="large"
                                        width={300}
                                        text="signin_with"
                                        shape="pill"
                                        useOneTap={false}
                                    />
                                </GoogleOAuthProvider>
                            )}
                        </ClientOnly>
                    </div>

                    <p className="text-xs text-center leading-relaxed" style={{ color: 'var(--color-text-sub)', opacity: 0.7 }}>
                        ระบบจะสร้างบัญชีให้อัตโนมัติเมื่อเข้าสู่ระบบครั้งแรก
                    </p>
                </div>
            </div>
        </div>
    )
}
