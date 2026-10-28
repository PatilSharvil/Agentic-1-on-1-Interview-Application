// Inline stroke icons — single stroke system: round caps, 1.8px, 24px grid.
const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export function IconMic({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="9" y="2.5" width="6" height="11.5" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3.5" />
    </svg>
  )
}

export function IconMicOff({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="9" y="2.5" width="6" height="11.5" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3.5" />
      <path d="M3.5 3.5 20.5 20.5" />
    </svg>
  )
}

export function IconCam({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="2.5" y="6" width="13" height="12" rx="3" />
      <path d="M15.5 10.5 21 7.5v9l-5.5-3" />
    </svg>
  )
}

export function IconCamOff({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="2.5" y="6" width="13" height="12" rx="3" />
      <path d="M15.5 10.5 21 7.5v9l-5.5-3" />
      <path d="M3.5 3.5 20.5 20.5" />
    </svg>
  )
}

export function IconScreen({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="2.5" y="4" width="19" height="13" rx="2.5" />
      <path d="M8 20.5h8" />
      <path d="M9.5 9.5 7 12l2.5 2.5" />
      <path d="M14 9.5 16.5 12 14 14.5" />
    </svg>
  )
}

export function IconRecord({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function IconStop({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function IconMonitorArrow({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M15 3.5H3.5v11H19" />
      <path d="M6.5 20.5h11" />
      <path d="M12 14.5 15 17.5" />
      <path d="M15 17.5v-4" />
      <path d="M22.5 8h-5" />
      <path d="m20 5.5 2.5 2.5L20 10.5" />
    </svg>
  )
}

export function IconLeave({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M13 5.5v13l6.5-5-6.5-5z" fill="none" />
      <path d="m13 7 6 5-6 5" />
      <path d="M9 3.5H4.5v17H9" />
    </svg>
  )
}

export function IconSend({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M4 12 21 3.5 17 20.5 11 13z" />
      <path d="M11 13 21 3.5" />
    </svg>
  )
}

export function IconUpload({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 16v3.5h16V16" />
    </svg>
  )
}

export function IconSpark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="M12 8.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z" />
    </svg>
  )
}

export function IconGraph({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="18" r="2.5" />
      <circle cx="12" cy="5.5" r="2.5" />
      <path d="M7.2 16 11 7.8M16.8 16 13 7.8" />
      <path d="M8.5 18h7" />
    </svg>
  )
}

export function IconExternal({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M13.5 4h6.5v6.5" />
      <path d="M20 4 11 13" />
      <path d="M18 14v5.5A1.5 1.5 0 0 1 16.5 21h-11A1.5 1.5 0 0 1 4 19.5v-11A1.5 1.5 0 0 1 5.5 7H11" />
    </svg>
  )
}

export function IconWave({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} aria-hidden="true">
      <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />
    </svg>
  )
}
