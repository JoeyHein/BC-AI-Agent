# BC AI Agent - Design System

**Inspired by**: Fyxer.com
**Design Philosophy**: Clean, minimalist, enterprise-grade reliability
**Target Audience**: Internal business users (7 users + 2 devs)

---

## Color Palette

### Primary Colors
```css
--color-primary: #1e3a8a;        /* Navy Blue - Main brand color */
--color-primary-hover: #1e40af;  /* Darker blue for hover states */
--color-primary-light: #3b82f6;  /* Light blue for accents */
```

### Neutral Colors
```css
--color-background: #ffffff;      /* Pure white background */
--color-surface: #f9fafb;         /* Light gray for cards/panels */
--color-border: #e5e7eb;          /* Border gray */
--color-text-primary: #111827;    /* Almost black for primary text */
--color-text-secondary: #6b7280;  /* Gray for secondary text */
--color-text-muted: #9ca3af;      /* Light gray for muted text */
```

### Semantic Colors
```css
--color-success: #10b981;         /* Green for success states */
--color-warning: #f59e0b;         /* Amber for warnings */
--color-error: #ef4444;           /* Red for errors */
--color-info: #3b82f6;            /* Blue for informational */
```

### AI-Specific Colors
```css
--color-ai-accent: #8b5cf6;      /* Purple for AI features */
--color-confidence-high: #10b981; /* Green for high confidence */
--color-confidence-medium: #f59e0b; /* Amber for medium confidence */
--color-confidence-low: #ef4444;  /* Red for low confidence */
```

---

## Typography

### Font Families
```css
--font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
--font-serif: 'Georgia', 'Times New Roman', serif;  /* For headlines */
--font-mono: 'SF Mono', 'Monaco', 'Inconsolata', 'Consolas', monospace;  /* For code */
```

### Font Sizes
```css
--text-xs: 0.75rem;    /* 12px - Labels, captions */
--text-sm: 0.875rem;   /* 14px - Secondary text */
--text-base: 1rem;     /* 16px - Body text */
--text-lg: 1.125rem;   /* 18px - Emphasized text */
--text-xl: 1.25rem;    /* 20px - Small headings */
--text-2xl: 1.5rem;    /* 24px - Section headers */
--text-3xl: 1.875rem;  /* 30px - Page titles */
--text-4xl: 2.25rem;   /* 36px - Hero text */
```

### Font Weights
```css
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

---

## Spacing System

Based on 4px grid:

```css
--space-1: 0.25rem;   /* 4px */
--space-2: 0.5rem;    /* 8px */
--space-3: 0.75rem;   /* 12px */
--space-4: 1rem;      /* 16px */
--space-5: 1.25rem;   /* 20px */
--space-6: 1.5rem;    /* 24px */
--space-8: 2rem;      /* 32px */
--space-10: 2.5rem;   /* 40px */
--space-12: 3rem;     /* 48px */
--space-16: 4rem;     /* 64px */
--space-20: 5rem;     /* 80px */
```

---

## Layout

### Container Widths
```css
--container-sm: 640px;   /* Mobile/small screens */
--container-md: 768px;   /* Tablets */
--container-lg: 1024px;  /* Desktop */
--container-xl: 1280px;  /* Large desktop */
--container-2xl: 1536px; /* Extra large */
```

### Grid System
- 12-column grid for layouts
- Responsive breakpoints: sm (640px), md (768px), lg (1024px), xl (1280px)

---

## Components

### Buttons

**Primary Button**:
```css
background: var(--color-primary);
color: white;
padding: 0.75rem 1.5rem;
border-radius: 0.5rem;
font-weight: 600;
transition: all 0.2s;

&:hover {
  background: var(--color-primary-hover);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}
```

**Secondary Button**:
```css
background: transparent;
color: var(--color-primary);
border: 2px solid var(--color-primary);
padding: 0.75rem 1.5rem;
border-radius: 0.5rem;
font-weight: 600;
```

**Ghost Button**:
```css
background: transparent;
color: var(--color-text-secondary);
padding: 0.75rem 1.5rem;

&:hover {
  background: var(--color-surface);
}
```

### Cards

```css
background: var(--color-surface);
border: 1px solid var(--color-border);
border-radius: 0.75rem;
padding: 1.5rem;
box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
transition: all 0.2s;

&:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}
```

### Input Fields

```css
background: white;
border: 1px solid var(--color-border);
border-radius: 0.5rem;
padding: 0.75rem 1rem;
font-size: var(--text-base);
transition: all 0.2s;

&:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(30, 58, 138, 0.1);
}
```

### Badges/Tags

**Confidence Score Badge**:
```jsx
// High Confidence (>0.8)
<Badge color="success">95% Confident</Badge>

// Medium Confidence (0.6-0.8)
<Badge color="warning">72% Confident</Badge>

// Low Confidence (<0.6)
<Badge color="error">45% Confident</Badge>
```

### Navigation

**Top Navigation**:
- Fixed header at top
- Logo left-aligned
- Navigation links center
- User profile/settings right-aligned
- Height: 64px
- Background: white with bottom border

**Sidebar Navigation**:
- Width: 256px (expanded), 64px (collapsed)
- Background: var(--color-surface)
- Icons + text when expanded
- Icons only when collapsed

---

## UI Patterns

### Dashboard Layout

```
┌─────────────────────────────────────────┐
│  Header (Logo, Nav, User)               │ 64px
├──────┬──────────────────────────────────┤
│      │                                   │
│ Side │  Main Content Area                │
│ Nav  │  - Stats Cards (Top)              │
│      │  - Data Tables/Lists (Middle)     │
│ 256  │  - Details Panel (Bottom)         │
│ px   │                                   │
│      │                                   │
└──────┴──────────────────────────────────┘
```

### Email List View

```jsx
<EmailList>
  <EmailCard
    sender="John Doe"
    subject="Quote Request - Aluminum Doors"
    preview="Hi, I need a quote for 5 doors..."
    timestamp="2 hours ago"
    status="pending"  // pending, parsed, quote_created
    confidence={0.92}
  />
</EmailList>
```

### Quote Review Interface

```jsx
<QuoteReview>
  <EmailPreview />
  <AIExtractedData
    confidence={0.92}
    fields={parsedData}
  />
  <BCQuoteDraft
    lines={quoteLines}
    total={$10,397.08}
  />
  <ApprovalActions>
    <Button primary>Approve & Create Quote</Button>
    <Button secondary>Edit Details</Button>
    <Button ghost>Reject</Button>
  </ApprovalActions>
</QuoteReview>
```

---

## AI Confidence Visualization

### Progress Bar Style
```jsx
<ConfidenceBar value={92}>
  <ConfidenceLabel>92% Confident</ConfidenceLabel>
  <ProgressBar>
    <Fill width="92%" color="success" />
  </ProgressBar>
</ConfidenceBar>
```

### Color Coding
- **90-100%**: Green (High confidence - auto-approve ready)
- **70-89%**: Amber (Medium - review recommended)
- **0-69%**: Red (Low - manual review required)

---

## Icons

**Icon Library**: Heroicons (v2)
- Matches Tailwind CSS ecosystem
- Clean, modern design
- Available in outline and solid variants

**Common Icons**:
- Email: `EnvelopeIcon`
- Quote: `DocumentTextIcon`
- Customer: `UserIcon`
- AI: `SparklesIcon`
- Success: `CheckCircleIcon`
- Warning: `ExclamationTriangleIcon`
- Settings: `CogIcon`

---

## Animation & Transitions

### Standard Transitions
```css
transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
```

### Hover Effects
- Slight elevation (translateY(-2px))
- Shadow increase
- Color darkening (for buttons)

### Loading States
- Skeleton screens (gray placeholders)
- Spinner for async operations
- Progress bar for multi-step processes

---

## Responsive Design

### Breakpoints
- **Mobile**: 0-640px (sm)
- **Tablet**: 641-1024px (md, lg)
- **Desktop**: 1025px+ (xl, 2xl)

### Mobile-First Approach
- Start with mobile layout
- Progressive enhancement for larger screens
- Collapsible sidebar on mobile
- Stack cards vertically on mobile

---

## Accessibility

### WCAG 2.1 Level AA Compliance
- Contrast ratio: 4.5:1 minimum for text
- Focus indicators visible on all interactive elements
- Keyboard navigation support
- ARIA labels for screen readers
- Alt text for all images

### Focus States
```css
&:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
```

---

## Dark Mode (Future Enhancement)

**NOT IMPLEMENTED IN PHASE 1**

Placeholder color scheme for future implementation:

```css
/* Dark mode colors */
--color-background-dark: #111827;
--color-surface-dark: #1f2937;
--color-text-primary-dark: #f9fafb;
--color-text-secondary-dark: #d1d5db;
```

---

## Component Library

**Recommended**: Shadcn/ui (Radix UI + Tailwind CSS)
- Unstyled, accessible components
- Easy customization
- TypeScript support
- Tree-shakeable

**Alternative**: Material-UI (MUI) - If more opinionated framework preferred

---

## Page Templates

### 1. Dashboard
- Stats overview (quotes processed, time saved, error rate)
- Recent activity feed
- Pending approvals queue

### 2. Email Queue
- List of incoming emails
- Filter by status (pending, parsed, created)
- Search by sender, subject
- Confidence score badges

### 3. Quote Review
- Email context panel (left)
- Extracted data panel (center)
- Quote preview panel (right)
- Approval workflow (bottom)

### 4. Quotes History
- Table of created quotes
- Filter by date, customer, status
- Export to CSV
- Link to BC quote

### 5. Settings
- Email inbox configuration
- AI confidence thresholds
- Notification preferences
- User management

---

## Usage Examples

### High-Confidence Email Card
```jsx
<Card className="border-l-4 border-green-500">
  <CardHeader>
    <Badge color="success">95% Confident</Badge>
    <EmailMeta sender="Overhead Door Regina" time="2h ago" />
  </CardHeader>
  <CardBody>
    <p className="text-gray-700">Quote request for 3 aluminum doors...</p>
    <ExtractedData>
      <DataField label="Customer" value="Overhead Door Regina" />
      <DataField label="Quantity" value="3 doors" />
      <DataField label="Total" value="$11,740.27" />
    </ExtractedData>
  </CardBody>
  <CardFooter>
    <Button primary>Review & Approve</Button>
  </CardFooter>
</Card>
```

### Low-Confidence Warning
```jsx
<Alert variant="warning" className="mb-4">
  <ExclamationTriangleIcon className="w-5 h-5" />
  <AlertTitle>Low Confidence (45%)</AlertTitle>
  <AlertDescription>
    Manual review required. AI couldn't confidently extract all fields.
  </AlertDescription>
</Alert>
```

---

## Development Guidelines

### CSS Framework
**Tailwind CSS 3.x**
- Utility-first approach
- Matches Fyxer aesthetic
- Easy customization
- Excellent developer experience

### Component Architecture
```
src/
├── components/
│   ├── ui/           # Base UI components (shadcn/ui)
│   ├── email/        # Email-specific components
│   ├── quote/        # Quote-specific components
│   ├── layout/       # Layout components
│   └── shared/       # Shared components
```

### State Management
**Zustand** (lightweight alternative to Redux)
- Simple API
- TypeScript support
- No boilerplate
- Perfect for medium-sized apps

### Data Fetching
**TanStack Query (React Query)**
- Server state management
- Caching
- Automatic refetching
- Optimistic updates

---

## References

- **Design Inspiration**: https://www.fyxer.com/
- **Icons**: https://heroicons.com/
- **Components**: https://ui.shadcn.com/
- **Tailwind CSS**: https://tailwindcss.com/

---

**Created**: December 23, 2025
**Version**: 1.0
**Status**: Ready for implementation
