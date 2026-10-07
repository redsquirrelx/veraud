interface IconProps {
  size?: number
}

function baseProps(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  } as const
}

export function ShieldIcon({ size = 16 }: IconProps) {  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M8 1.5 13 3.5v4c0 3.5-2.5 5.8-5 7-2.5-1.2-5-3.5-5-7v-4L8 1.5Z" />
      <path d="m5.8 7.8 1.6 1.6 2.8-3" />
    </svg>
  )
}

export function GridIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <rect x="1.5" y="1.5" width="5" height="5" rx="1" />
      <rect x="9.5" y="1.5" width="5" height="5" rx="1" />
      <rect x="1.5" y="9.5" width="5" height="5" rx="1" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
    </svg>
  )
}

export function SlidersIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M2 5h12M2 11h12" />
      <circle cx="6" cy="5" r="1.8" fill="currentColor" stroke="none" />
      <circle cx="10" cy="11" r="1.8" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function CloneIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M8 2v8m0 0 3-3m-3 3L5 7" />
      <path d="M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" />
    </svg>
  )
}

export function CheckIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" />
      <path d="m5.2 8.2 2 2 3.6-4" />
    </svg>
  )
}

export function CrossIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" />
      <path d="m6 6 4 4m0-4-4 4" />
    </svg>
  )
}

export function ChevronDownIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m4 6 4 4 4-4" />
    </svg>
  )
}

export function ChevronUpIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m4 10 4-4 4 4" />
    </svg>
  )
}

export function ChevronLeftIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m10 4-4 4 4 4" />
    </svg>
  )
}

export function ChevronRightIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m6 4 4 4-4 4" />
    </svg>
  )
}

export function XIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m4 4 8 8m0-4-8 8" />
    </svg>
  )
}

export function FolderIcon({ size = 16 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M1.5 4.5a1 1 0 0 1 1-1h4l1.5 2h5.5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-7Z" />
    </svg>
  )
}

export function RefreshIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 1.5v3h-3" />
    </svg>
  )
}

export function SortIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M2 4.5h12M2 8h8M2 11.5h5" />
    </svg>
  )
}

export function ArrowUpIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M8 13.5v-11m0 0-3.5 3.5M8 2.5l3.5 3.5" />
    </svg>
  )
}

export function ArrowDownIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M8 2.5v11m0 0 3.5-3.5M8 13.5 4.5 10" />
    </svg>
  )
}

export function ArrowRightIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M2.5 8h11m0 0-3.5-3.5M13.5 8 10 11.5" />
    </svg>
  )
}

export function DotsIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <circle cx="8" cy="3" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="8" cy="13" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function DatabaseIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <ellipse cx="8" cy="4" rx="5" ry="2" />
      <path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4" />
      <path d="M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" />
    </svg>
  )
}

export function ListIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M5.5 4h8M5.5 8h8M5.5 12h8" />
      <circle cx="2.5" cy="4" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="2.5" cy="8" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="2.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function CodeIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="m6 5-3 3 3 3M10 5l3 3-3 3" />
    </svg>
  )
}

export function TypeIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M4 13.5 8 2.5l4 11M5.3 10h5.4" />
    </svg>
  )
}

export function LockIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <rect x="3.5" y="7" width="9" height="6.5" rx="1" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  )
}

export function PinIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M8 14.5s5-4.6 5-8a5 5 0 1 0-10 0c0 3.4 5 8 5 8Z" />
      <circle cx="8" cy="6.5" r="1.8" />
    </svg>
  )
}

export function ExternalIcon({ size = 14 }: IconProps) {
  return (
    <svg {...baseProps(size)} aria-hidden="true">
      <path d="M9.5 2.5h4v4" />
      <path d="M13.5 2.5 7.5 8.5" />
      <path d="M11.5 6.5v5a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h5" />
    </svg>
  )
}
