import { useState, useEffect, useRef, useCallback, createContext, useContext } from 'react';
import { partFinder, isAuthed } from './api';
import './partfinder.css';

// Where the "Sign in" links point. Host apps inject their own login route via
// the `signInHref` prop; defaults to /login. Kept in context so the gating
// sub-components don't need it threaded through every level.
const SignInContext = createContext('/login');
const useSignInHref = () => useContext(SignInContext);

/* ----------------------------------------------------------- offline queue */
const FEEDBACK_QUEUE_KEY = 'pf-feedback-queue';

function enqueueFeedback(payload) {
  try {
    const q = JSON.parse(localStorage.getItem(FEEDBACK_QUEUE_KEY) || '[]');
    q.push(payload);
    localStorage.setItem(FEEDBACK_QUEUE_KEY, JSON.stringify(q));
  } catch {}
}

async function drainFeedbackQueue() {
  try {
    const q = JSON.parse(localStorage.getItem(FEEDBACK_QUEUE_KEY) || '[]');
    if (!q.length) return;
    const remaining = [];
    for (const payload of q) {
      try {
        await partFinder.feedback(payload);
      } catch {
        remaining.push(payload);
      }
    }
    if (remaining.length) {
      localStorage.setItem(FEEDBACK_QUEUE_KEY, JSON.stringify(remaining));
    } else {
      localStorage.removeItem(FEEDBACK_QUEUE_KEY);
    }
  } catch {}
}

const CATEGORY_HINTS = [
  'Garage Door Panels',
  'Garage Door Operators',
  'Garage Door Springs',
  'Garage Door Hardware',
  'Dock Equipment',
  'Dock Seals & Shelters',
];

const ALL_MODES = [
  { id: 'photo', label: 'Identify by photo', sub: 'Upload a picture' },
  { id: 'narrow', label: 'Narrow it down', sub: 'Step by step' },
  { id: 'browse', label: 'Browse brands', sub: '76 manufacturers' },
  { id: 'search', label: 'Search', sub: 'Text or part #' },
  { id: 'history', label: 'Recent lookups', sub: 'Your history', authOnly: true },
];

export default function PartFinder({ signInHref = '/login' }) {
  const [mode, setMode] = useState('photo');
  const [stats, setStats] = useState(null);
  const [activeDoc, setActiveDoc] = useState(null);
  const authed = isAuthed();

  const MODES = ALL_MODES.filter((m) => !m.authOnly || authed);

  useEffect(() => {
    partFinder.stats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    const onOnline = () => drainFeedbackQueue();
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, []);

  return (
    <SignInContext.Provider value={signInHref}>
    <div className="pf-root">
      <Backdrop />
      <TopBar stats={stats} authed={authed} />
      <OfflineBanner />

      <header className="pf-hero">
        <div className="pf-hero-inner">
          <p className="pf-eyebrow">OPENDC · Equipment Identification</p>
          <h1 className="pf-title">
            Identify any <span>door or dock</span> part.
          </h1>
          <p className="pf-lede">
            Snap a photo, narrow by brand, or look up a model number — and pull the exact
            manual from {stats ? stats.documents.toLocaleString() : '340'} indexed manufacturer documents.
          </p>

          <nav className="pf-tabs" role="tablist">
            {MODES.map((m, i) => (
              <button
                key={m.id}
                role="tab"
                aria-selected={mode === m.id}
                className={`pf-tab ${mode === m.id ? 'is-active' : ''}`}
                style={{ animationDelay: `${i * 70}ms` }}
                onClick={() => setMode(m.id)}
              >
                <span className="pf-tab-idx">{String(i + 1).padStart(2, '0')}</span>
                <span className="pf-tab-label">{m.label}</span>
                <span className="pf-tab-sub">{m.sub}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="pf-main">
        {mode === 'photo' && <PhotoMode onOpen={setActiveDoc} authed={authed} />}
        {mode === 'narrow' && <WizardMode onOpen={setActiveDoc} />}
        {mode === 'browse' && <BrowseMode onOpen={setActiveDoc} />}
        {mode === 'search' && <SearchMode onOpen={setActiveDoc} authed={authed} />}
        {mode === 'history' && <HistoryMode onOpen={setActiveDoc} />}
      </main>

      <footer className="pf-footer">
        <span>OPENDC Part Finder</span>
        <span className="pf-dot">·</span>
        <span>{stats ? `${stats.pages.toLocaleString()} pages · ${stats.brands} brands · ${stats.part_numbers.toLocaleString()} part numbers` : 'loading index…'}</span>
      </footer>

      {activeDoc && <DocDrawer docId={activeDoc} authed={authed} onClose={() => setActiveDoc(null)} />}
    </div>
    </SignInContext.Provider>
  );
}

/* ----------------------------------------------------------------- chrome */
function Backdrop() {
  return <div className="pf-backdrop" aria-hidden="true" />;
}

function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, []);
  if (online) return null;
  return (
    <div className="pf-offline-banner" role="alert">
      No network — identification and search require connectivity. Cached pages load normally.
    </div>
  );
}

function TopBar({ stats, authed }) {
  const signInHref = useSignInHref();
  return (
    <div className="pf-topbar">
      <div className="pf-brand">
        <span className="pf-brand-mark">◧</span>
        OPEN<span className="pf-brand-accent">DC</span>
        <span className="pf-brand-divider" />
        <span className="pf-brand-sub">PART FINDER</span>
      </div>
      <div className="pf-topbar-right">
        {stats && (
          <span className="pf-stat-chip">
            {stats.documents.toLocaleString()} docs indexed
          </span>
        )}
        {authed ? (
          <span className="pf-badge-full">● Full access</span>
        ) : (
          <a className="pf-signin" href={signInHref}>Sign in</a>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ photo */
// "I'm not sure" sentinel — scans across every category (the original behavior).
const ANY_CATEGORY = { category: '', label: "I'm not sure", meta: 'Search every category' };

function PhotoMode({ onOpen, authed }) {
  const [chosenCat, setChosenCat] = useState(null);
  const [face, setFace] = useState(null);
  const [facePrev, setFacePrev] = useState(null);
  const [side, setSide] = useState(null);
  const [sidePrev, setSidePrev] = useState(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  // The prominent one-hand camera button targets the face slot; the side slot
  // is reached by tapping it directly.
  const faceInputRef = useRef(null);

  // Panels are the category where the edge-on side profile (thickness + joint
  // profile) is the real discriminator, so we lead with it there.
  const isPanels = (chosenCat?.category || '').startsWith('01');

  const chooseFace = (f) => { if (!f) return; setFace(f); setFacePrev(URL.createObjectURL(f)); setResult(null); setError(null); };
  const chooseSide = (f) => { if (!f) return; setSide(f); setSidePrev(URL.createObjectURL(f)); setResult(null); setError(null); };

  const changeCategory = () => {
    setChosenCat(null);
    setFace(null); setFacePrev(null);
    setSide(null); setSidePrev(null);
    setResult(null); setError(null);
  };

  const run = async () => {
    if (!face) return;
    setLoading(true);
    setError(null);
    try {
      const r = await partFinder.identify({ file: face, sideFile: side, category: chosenCat?.category || '', note });
      setResult(r);
    } catch (e) {
      setError(!navigator.onLine
        ? "You're offline — connect to identify parts."
        : (e.body?.detail?.detail || e.message));
    } finally {
      setLoading(false);
    }
  };

  // Step 1 — pick what you're looking at.
  if (!chosenCat) {
    return <CategoryPicker onPick={setChosenCat} />;
  }

  // Step 2 — upload + identify, scoped to the chosen category.
  const scopedLabel = chosenCat.category ? chosenCat.label : null;
  return (
    <div className="pf-panel pf-grid-2">
      <section className="pf-card pf-uploader">
        <div className="pf-scope-bar">
          <span className="pf-kicker">Looking at</span>
          <span className="pf-chip pf-chip-cat">{chosenCat.label}</span>
          <button className="pf-scope-change" onClick={changeCategory}>Change</button>
        </div>

        <div className="pf-slots">
          <DropSlot label="Face / front" hint="Straight-on view" preview={facePrev} onChoose={chooseFace} inputRef={faceInputRef} />
          <DropSlot
            label="Side profile"
            hint={isPanels ? 'Shows thickness & joint' : 'Optional · edge-on view'}
            preview={sidePrev}
            onChoose={chooseSide}
            emphasized={isPanels}
          />
        </div>
        {isPanels && !side && (
          <p className="pf-slot-tip">For panels, the side profile is the best way to tell thickness and joint type apart — add one if you can.</p>
        )}

        <button
          className="pf-cam-btn"
          type="button"
          onClick={() => faceInputRef.current?.click()}
          aria-label={face ? 'Change face photo' : 'Take a face photo'}
        >
          <span aria-hidden="true">📷</span>
          {face ? 'Change Face Photo' : 'Take Photo'}
        </button>

        <label className="pf-field">
          <span>Anything you can read on it? (optional)</span>
          <input
            type="text"
            placeholder="e.g. label says LiftMaster, model 8500"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>

        <button className="pf-btn-primary" disabled={!face || loading} onClick={run}>
          {loading ? 'Analyzing…' : 'Identify this product'}
        </button>
        {error && <p className="pf-error">{error}</p>}
      </section>

      <section className="pf-results-col">
        {!result && !loading && (
          <div className="pf-empty">
            <p className="pf-empty-big">Visual identification</p>
            <p>We’re focused on <strong>{chosenCat.label}</strong> — narrowing to one
              category makes the read sharper. Add a side-profile photo{isPanels ? ' (the key cue for panels)' : ''} and
              we’ll match against the catalog, then link you to the right manual.</p>
          </div>
        )}
        {loading && <SkeletonCards n={2} />}
        {result && <IdentifyResult result={result} onOpen={onOpen} authed={authed} scopedLabel={scopedLabel} />}
      </section>
    </div>
  );
}

function DropSlot({ label, hint, preview, onChoose, emphasized, inputRef }) {
  const [drag, setDrag] = useState(false);
  const localRef = useRef(null);
  const ref = inputRef || localRef;
  return (
    <div className="pf-slot">
      <div className="pf-slot-head">
        <span className="pf-slot-label">{label}</span>
        {emphasized && <span className="pf-slot-badge">Recommended</span>}
      </div>
      <div
        className={`pf-drop pf-drop-sm ${drag ? 'is-drag' : ''} ${preview ? 'has-img' : ''} ${emphasized ? 'is-emph' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onChoose(e.dataTransfer.files[0]); }}
        onClick={() => ref.current?.click()}
      >
        {preview ? (
          <img src={preview} alt={`${label} preview`} className="pf-preview" />
        ) : (
          <>
            <div className="pf-drop-icon">⤓</div>
            <p className="pf-drop-sub">{hint}</p>
          </>
        )}
        <input ref={ref} type="file" accept="image/*" capture="environment" hidden onChange={(e) => onChoose(e.target.files[0])} />
      </div>
    </div>
  );
}

function CategoryPicker({ onPick }) {
  const [cats, setCats] = useState(null);

  useEffect(() => {
    partFinder.facets()
      .then((f) => setCats(f.categories.map((c) => ({
        category: c.category, label: c.label, meta: `${c.count} manuals`,
      }))))
      .catch(() => setCats(CATEGORY_HINTS.map((label) => ({ category: label, label, meta: '' }))));
  }, []);

  return (
    <div className="pf-panel">
      <div className="pf-opt-block">
        <h3 className="pf-section-title">What are you looking at?</h3>
        <p className="pf-subtitle">Pick a category so we can scan faster and zero in on the right product.</p>
        {cats === null ? (
          <SkeletonCards n={3} />
        ) : (
          <div className="pf-opt-grid">
            {cats.map((o, i) => (
              <button key={o.category || o.label} className="pf-opt" style={{ animationDelay: `${i * 35}ms` }} onClick={() => onPick(o)}>
                <span className="pf-opt-label">{o.label}</span>
                <span className="pf-opt-meta">{o.meta}</span>
              </button>
            ))}
            <button className="pf-opt pf-opt-any" style={{ animationDelay: `${cats.length * 35}ms` }} onClick={() => onPick(ANY_CATEGORY)}>
              <span className="pf-opt-label">{ANY_CATEGORY.label}</span>
              <span className="pf-opt-meta">{ANY_CATEGORY.meta}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function IdentifyResult({ result, onOpen, authed, scopedLabel }) {
  const cands = result.candidates || [];
  const mismatch = scopedLabel && result.category &&
    result.category.toLowerCase() !== scopedLabel.toLowerCase() &&
    result.category.toLowerCase() !== 'unknown';
  return (
    <div className="pf-stack">
      {mismatch && (
        <div className="pf-mismatch">
          <span className="pf-mismatch-mark">!</span>
          <p>This looks more like a <strong>{result.category}</strong> than a {scopedLabel}.
            We widened the search — or <em>Change</em> the category to refocus.</p>
        </div>
      )}
      <div className="pf-card pf-summary">
        <span className="pf-kicker">Best read</span>
        <h3>{result.product_summary || result.category}</h3>
        <div className="pf-chips">
          <span className="pf-chip pf-chip-cat">{result.category}</span>
          {(result.visible_features || []).slice(0, 6).map((f, i) => (
            <span key={i} className="pf-chip">{f}</span>
          ))}
        </div>
        {(result.readable_text || []).length > 0 && (
          <p className="pf-readable">
            Text on product: {result.readable_text.map((t, i) => <code key={i}>{t}</code>)}
          </p>
        )}
        {result.advice && <p className="pf-advice">→ {result.advice}</p>}
      </div>

      {cands.map((c, i) => (
        <article key={i} className="pf-card pf-candidate" style={{ animationDelay: `${i * 80}ms` }}>
          <div className="pf-cand-head">
            <div>
              <span className="pf-rank">#{i + 1}</span>
              <h4>{c.brand}</h4>
              {c.family_or_model && <span className="pf-model">{c.family_or_model}</span>}
            </div>
            <ConfidenceDial value={c.confidence} />
          </div>
          {c.reasoning && <p className="pf-reason">{c.reasoning}</p>}

          {(c.catalog_matches || []).length > 0 && (
            <div className="pf-matches">
              <span className="pf-kicker">Matching manuals</span>
              {c.catalog_matches.map((d) => (
                <button key={d.doc_id} className="pf-match-row" onClick={() => onOpen(d.doc_id)}>
                  <span className="pf-match-type">{d.doc_type || 'Doc'}</span>
                  <span className="pf-match-title">{d.title || d.filename}</span>
                  <span className="pf-match-arrow">→</span>
                </button>
              ))}
              {!authed && c.catalog_matches_total > c.catalog_matches.length && (
                <LockNote n={c.catalog_matches_total - c.catalog_matches.length} />
              )}
            </div>
          )}
        </article>
      ))}
      {result.locked && !authed && <UpgradeBanner message={result.upgrade_message} />}
      {result.photo_hash && <FeedbackWidget result={result} />}
    </div>
  );
}

function FeedbackWidget({ result }) {
  const [state, setState] = useState('idle'); // idle | correcting | submitting | done | error
  const [correctBrand, setCorrectBrand] = useState('');
  const [customBrand, setCustomBrand] = useState('');

  const cands = result.candidates || [];
  const candidateNames = [...new Set(cands.map((c) => c.brand).filter(Boolean))];

  const submit = async (wasCorrect, brand = null) => {
    setState('submitting');
    const payload = {
      photo_hash: result.photo_hash,
      candidates_shown: cands.map((c) => ({
        brand: c.brand,
        family_or_model: c.family_or_model || null,
        confidence: c.confidence ?? null,
      })),
      was_correct: wasCorrect,
      correct_brand: brand,
    };
    try {
      await partFinder.feedback(payload);
      setState('done');
    } catch {
      if (!navigator.onLine) {
        enqueueFeedback(payload);
        setState('done');
      } else {
        setState('error');
      }
    }
  };

  if (state === 'done') {
    return <div className="pf-feedback pf-feedback-done">Thanks for the feedback!</div>;
  }
  if (state === 'error') {
    return <div className="pf-feedback pf-feedback-done pf-feedback-error">Couldn't save — try again later.</div>;
  }

  if (state === 'correcting') {
    const selectedBrand = correctBrand === '__other__' ? customBrand.trim() : correctBrand;
    return (
      <div className="pf-feedback pf-feedback-correct">
        <span className="pf-feedback-label">Which brand is it?</span>
        <select
          className="pf-feedback-select"
          value={correctBrand}
          onChange={(e) => setCorrectBrand(e.target.value)}
        >
          <option value="">Select…</option>
          {candidateNames.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
          <option value="__other__">Other brand</option>
        </select>
        {correctBrand === '__other__' && (
          <input
            className="pf-feedback-input"
            placeholder="Brand name"
            value={customBrand}
            onChange={(e) => setCustomBrand(e.target.value)}
          />
        )}
        <div className="pf-feedback-actions">
          <button
            className="pf-btn-primary pf-feedback-submit"
            disabled={state === 'submitting' || !selectedBrand}
            onClick={() => submit(false, selectedBrand)}
          >
            Submit
          </button>
          <button className="pf-feedback-cancel" onClick={() => setState('idle')}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className="pf-feedback">
      <span className="pf-feedback-label">Was this right?</span>
      <button
        className="pf-feedback-btn pf-feedback-yes"
        disabled={state === 'submitting'}
        onClick={() => submit(true, null)}
        title="Yes, correct"
      >✓</button>
      <button
        className="pf-feedback-btn pf-feedback-no"
        disabled={state === 'submitting'}
        onClick={() => setState('correcting')}
        title="No, wrong"
      >✗</button>
    </div>
  );
}

function ConfidenceDial({ value = 0 }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="pf-dial" title={`${pct}% confidence`}>
      <svg viewBox="0 0 36 36">
        <path className="pf-dial-bg" d="M18 2 a16 16 0 0 1 0 32 a16 16 0 0 1 0 -32" />
        <path
          className="pf-dial-fg"
          d="M18 2 a16 16 0 0 1 0 32 a16 16 0 0 1 0 -32"
          strokeDasharray={`${pct}, 100`}
        />
      </svg>
      <span className="pf-dial-num">{pct}<small>%</small></span>
    </div>
  );
}

/* ----------------------------------------------------------------- wizard */
function WizardMode({ onOpen }) {
  const [facets, setFacets] = useState(null);
  const [cat, setCat] = useState(null);
  const [region, setRegion] = useState(null);
  const [brand, setBrand] = useState(null);
  const [brands, setBrands] = useState([]);
  const [docs, setDocs] = useState(null);

  useEffect(() => { partFinder.facets().then(setFacets).catch(() => {}); }, []);

  useEffect(() => {
    if (cat) {
      const params = { category: cat.category };
      if (region) params.region = region;
      partFinder.brands(params).then((r) => setBrands(r.brands)).catch(() => setBrands([]));
    }
  }, [cat, region]);

  useEffect(() => {
    if (cat && brand) {
      partFinder.documents({ category: cat.category, brand, limit: 100 })
        .then((r) => setDocs(r.documents)).catch(() => setDocs([]));
    }
  }, [brand]);

  const reset = (level) => {
    if (level <= 1) { setCat(null); }
    if (level <= 2) { setRegion(null); }
    if (level <= 3) { setBrand(null); setDocs(null); }
  };

  if (!facets) return <div className="pf-panel"><SkeletonCards n={3} /></div>;

  return (
    <div className="pf-panel">
      <div className="pf-breadcrumb">
        <Crumb active={!cat} label="Category" onClick={() => reset(1)} value={cat?.label} />
        <Crumb active={cat && !brand} label="Region" onClick={() => reset(2)} value={region} optional />
        <Crumb active={cat && !brand} label="Brand" onClick={() => reset(3)} value={brand} />
        <Crumb active={!!brand} label="Document" />
      </div>

      {!cat && (
        <OptionGrid
          title="What kind of equipment is it?"
          options={facets.categories.map((c) => ({ key: c.category, label: c.label, meta: `${c.count} docs`, raw: c }))}
          onPick={(o) => setCat(o.raw)}
        />
      )}

      {cat && !brand && (
        <>
          <div className="pf-region-row">
            <span className="pf-kicker">Region</span>
            <div className="pf-pills">
              <button className={`pf-pill ${!region ? 'is-on' : ''}`} onClick={() => setRegion(null)}>Any</button>
              {facets.regions.map((r) => (
                <button key={r} className={`pf-pill ${region === r ? 'is-on' : ''}`} onClick={() => setRegion(r)}>
                  {r.replace('-', ' ')}
                </button>
              ))}
            </div>
          </div>
          <OptionGrid
            title="Pick the brand"
            options={brands.map((b) => ({
              key: b.brand, label: b.brand,
              meta: `${b.doc_count} doc${b.doc_count > 1 ? 's' : ''}`,
              tag: b.brand_status,
            }))}
            onPick={(o) => setBrand(o.key)}
            empty="No brands for this filter."
          />
        </>
      )}

      {brand && (
        <DocGrid docs={docs} onOpen={onOpen} title={`${brand} — documents`} />
      )}
    </div>
  );
}

function Crumb({ active, label, value, onClick, optional }) {
  return (
    <button className={`pf-crumb ${active ? 'is-active' : ''} ${value ? 'has-val' : ''}`} onClick={onClick} disabled={!onClick}>
      <span className="pf-crumb-label">{label}{optional && <i> (opt)</i>}</span>
      {value && <span className="pf-crumb-val">{value}</span>}
    </button>
  );
}

function OptionGrid({ title, options, onPick, empty }) {
  return (
    <div className="pf-opt-block">
      <h3 className="pf-section-title">{title}</h3>
      {options.length === 0 ? (
        <p className="pf-muted">{empty || 'Nothing here.'}</p>
      ) : (
        <div className="pf-opt-grid">
          {options.map((o, i) => (
            <button key={o.key} className="pf-opt" style={{ animationDelay: `${i * 35}ms` }} onClick={() => onPick(o)}>
              <span className="pf-opt-label">{o.label}</span>
              <span className="pf-opt-meta">{o.meta}</span>
              {o.tag && o.tag !== 'Active' && <span className="pf-opt-tag">{o.tag}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ browse */
function BrowseMode({ onOpen }) {
  const [brands, setBrands] = useState([]);
  const [filter, setFilter] = useState('');
  const [openBrand, setOpenBrand] = useState(null);
  const [docs, setDocs] = useState(null);

  useEffect(() => { partFinder.brands().then((r) => setBrands(r.brands)).catch(() => {}); }, []);

  const open = (b) => {
    setOpenBrand(b);
    setDocs(null);
    partFinder.documents({ brand: b.brand, limit: 100 }).then((r) => setDocs(r.documents)).catch(() => setDocs([]));
  };

  const groups = {};
  brands
    .filter((b) => b.brand.toLowerCase().includes(filter.toLowerCase()) ||
      (b.manufacturer || '').toLowerCase().includes(filter.toLowerCase()))
    .forEach((b) => { (groups[b.category_label] ||= []).push(b); });

  if (openBrand) {
    return (
      <div className="pf-panel">
        <button className="pf-back" onClick={() => setOpenBrand(null)}>← All brands</button>
        <DocGrid docs={docs} onOpen={onOpen}
          title={openBrand.manufacturer || openBrand.brand}
          subtitle={[openBrand.parent_company, openBrand.product_lines].filter(Boolean).join(' · ')} />
      </div>
    );
  }

  return (
    <div className="pf-panel">
      <input className="pf-search-input" placeholder="Filter brands…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      {Object.entries(groups).map(([label, list]) => (
        <div key={label} className="pf-brand-group">
          <h3 className="pf-section-title">{label} <span className="pf-count">{list.length}</span></h3>
          <div className="pf-opt-grid">
            {list.map((b, i) => (
              <button key={b.brand + b.category} className="pf-opt" style={{ animationDelay: `${i * 25}ms` }} onClick={() => open(b)}>
                <span className="pf-opt-label">{b.brand}</span>
                <span className="pf-opt-meta">{b.doc_count} doc{b.doc_count > 1 ? 's' : ''}</span>
                {b.brand_status && b.brand_status !== 'Active' && <span className="pf-opt-tag">{b.brand_status}</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ search */
function SearchMode({ onOpen, authed }) {
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [pn, setPn] = useState(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef(null);

  const run = useCallback(async (term) => {
    if (term.trim().length < 2) { setData(null); setPn(null); return; }
    setLoading(true);
    try {
      const looksLikePart = /\d/.test(term) && term.trim().length <= 18 && !term.includes(' ');
      const [fts, partRes] = await Promise.all([
        partFinder.search(term).catch(() => null),
        looksLikePart ? partFinder.partNumber(term).catch(() => null) : Promise.resolve(null),
      ]);
      setData(fts);
      setPn(partRes && partRes.total > 0 ? partRes : null);
    } finally {
      setLoading(false);
    }
  }, []);

  const onChange = (v) => {
    setQ(v);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => run(v), 350);
  };

  return (
    <div className="pf-panel">
      <div className="pf-search-bar">
        <span className="pf-search-icon">⌕</span>
        <input
          autoFocus
          className="pf-search-input pf-search-big"
          placeholder="Search manuals or enter a model / part number  (e.g. “torsion spring”, AL976, 8500W)"
          value={q}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>

      {loading && <SkeletonCards n={3} />}

      {pn && (
        <div className="pf-pn-block">
          <h3 className="pf-section-title">Part number <code className="pf-pn-token">{pn.token}</code> appears in</h3>
          <DocGrid docs={pn.results} onOpen={onOpen} compact />
          {pn.locked && !authed && <UpgradeBanner message={pn.upgrade_message} small />}
          <BuyLinksBar token={pn.token} />
        </div>
      )}

      {data && (
        <div>
          <h3 className="pf-section-title">{data.total} document{data.total !== 1 ? 's' : ''} mention “{data.query}”</h3>
          <div className="pf-stack">
            {data.results.map((r, i) => (
              <button key={r.doc_id} className="pf-card pf-search-row" style={{ animationDelay: `${i * 40}ms` }} onClick={() => onOpen(r.doc_id)}>
                <div className="pf-search-meta">
                  <span className="pf-chip pf-chip-cat">{r.category_label}</span>
                  {r.brand && <span className="pf-search-brand">{r.brand}</span>}
                  <span className="pf-search-page">p.{r.match_page}</span>
                </div>
                <p className="pf-search-title">{r.title || r.filename}</p>
                <p className="pf-snippet" dangerouslySetInnerHTML={{ __html: r.snippet }} />
              </button>
            ))}
          </div>
          {data.locked && !authed && <UpgradeBanner message={data.upgrade_message} />}
        </div>
      )}

      {!loading && !data && !pn && q.length < 2 && (
        <div className="pf-empty">
          <p className="pf-empty-big">Full-text + part-number search</p>
          <p>Search across {`8,000+`} pages of manuals, or type a model/part number to find
            exactly which document covers it.</p>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ shared bits */
function DocGrid({ docs, onOpen, title, subtitle, compact }) {
  if (docs === null) return <SkeletonCards n={4} />;
  return (
    <div>
      {title && <h3 className="pf-section-title">{title}</h3>}
      {subtitle && <p className="pf-subtitle">{subtitle}</p>}
      {docs.length === 0 ? (
        <p className="pf-muted">No documents found.</p>
      ) : (
        <div className={`pf-doc-grid ${compact ? 'is-compact' : ''}`}>
          {docs.map((d, i) => (
            <button key={d.doc_id} className="pf-doc" style={{ animationDelay: `${i * 30}ms` }} onClick={() => onOpen(d.doc_id)}>
              <div className="pf-doc-cover">
                {d.cover_image
                  ? <img src={partFinder.coverUrl(d.doc_id)} alt="" loading="lazy" />
                  : <div className="pf-doc-nocover">{d.doc_type || 'PDF'}</div>}
                <span className="pf-doc-pages">{d.page_count}p</span>
              </div>
              <div className="pf-doc-body">
                <span className="pf-doc-type">{d.doc_type || 'Document'}</span>
                <p className="pf-doc-title">{d.title || d.filename}</p>
                {d.brand && <span className="pf-doc-brand">{d.brand}</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------- buy-links bar */
function BuyLinksBar({ token }) {
  const [links, setLinks] = useState(null);
  useEffect(() => {
    partFinder.buyLinks(token).then(setLinks).catch(() => setLinks({ links: [] }));
  }, [token]);
  if (!links) return null;
  if (!links.links?.length) return null;
  return (
    <div className="pf-buy-bar">
      <span className="pf-kicker">Find this part at</span>
      <div className="pf-buy-links">
        {links.links.map((l) => (
          <a
            key={l.logo_key}
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="pf-buy-link"
          >
            {l.name}
          </a>
        ))}
      </div>
    </div>
  );
}

function DocDrawer({ docId, authed, onClose }) {
  const signInHref = useSignInHref();
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setDoc(null);
    partFinder.document(docId).then(setDoc).catch((e) => setErr(e.message));
  }, [docId]);

  const openPdf = async () => {
    if (!authed) return;
    try {
      const { url, mode } = await partFinder.openManual(docId);
      if (mode === 'link-out') {
        window.open(url, '_blank', 'noopener,noreferrer');
      } else {
        // serve mode: fetch as blob with auth header
        const t = localStorage.getItem('authToken');
        const r = await fetch(partFinder.pdfUrl(docId), { headers: { Authorization: `Bearer ${t}` } });
        const b = await r.blob();
        window.open(URL.createObjectURL(b), '_blank');
      }
    } catch (_) {}
  };

  return (
    <div className="pf-drawer-wrap" onClick={onClose}>
      <aside className="pf-drawer" onClick={(e) => e.stopPropagation()}>
        <button className="pf-drawer-close" onClick={onClose}>✕</button>
        {!doc && !err && <SkeletonCards n={1} />}
        {err && <p className="pf-error">{err}</p>}
        {doc && (
          <>
            <div className="pf-drawer-cover">
              {doc.cover_image
                ? <img src={partFinder.coverUrl(doc.doc_id)} alt="" />
                : <div className="pf-doc-nocover lg">{doc.doc_type || 'PDF'}</div>}
            </div>
            <span className="pf-doc-type">{doc.doc_type || 'Document'} · {doc.page_count} pages</span>
            <h2 className="pf-drawer-title">{doc.title || doc.filename}</h2>

            <div className="pf-meta-rows">
              {doc.manufacturer && <MetaRow k="Manufacturer" v={doc.manufacturer} />}
              {doc.brand && <MetaRow k="Brand" v={doc.brand} />}
              {doc.parent_company && <MetaRow k="Parent" v={doc.parent_company} />}
              {doc.category_label && <MetaRow k="Category" v={doc.category_label} />}
              {doc.region && <MetaRow k="Region" v={doc.region.replace('-', ' ')} />}
              {doc.brand_status && <MetaRow k="Status" v={doc.brand_status} />}
              {doc.product_lines && <MetaRow k="Product lines" v={doc.product_lines} />}
            </div>

            {(doc.part_numbers || []).length > 0 && (
              <div className="pf-pn-list">
                <span className="pf-kicker">
                  Part / model numbers{doc.part_numbers_total ? ` (${doc.part_numbers_total})` : ''}
                </span>
                <div className="pf-pn-tokens">
                  {doc.part_numbers.map((p, i) => (
                    <code key={i} className="pf-pn">{p.token}</code>
                  ))}
                </div>
                {doc.locked && !authed && <LockNote n={(doc.part_numbers_total || 0) - doc.part_numbers.length} label="more part numbers" />}
              </div>
            )}

            {authed ? (
              <button className="pf-btn-primary pf-open-pdf" onClick={openPdf}>Open manual (PDF)</button>
            ) : (
              <a className="pf-btn-locked" href={signInHref}>
                <span className="pf-lock">🔒</span> Sign in to open the manual
              </a>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

function MetaRow({ k, v }) {
  return (
    <div className="pf-meta-row">
      <span className="pf-meta-k">{k}</span>
      <span className="pf-meta-v">{v}</span>
    </div>
  );
}

function UpgradeBanner({ message, small }) {
  const signInHref = useSignInHref();
  return (
    <div className={`pf-upgrade ${small ? 'is-small' : ''}`}>
      <span className="pf-lock">🔒</span>
      <p>{message || 'Sign in to unlock all results.'}</p>
      <a href={signInHref} className="pf-upgrade-btn">Sign in</a>
    </div>
  );
}

function LockNote({ n, label = 'more matches' }) {
  const signInHref = useSignInHref();
  return (
    <a href={signInHref} className="pf-locknote">
      <span className="pf-lock">🔒</span> +{n} {label} — sign in to view
    </a>
  );
}

/* --------------------------------------------------------------- history */
function HistoryMode({ onOpen }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    partFinder.history(20)
      .then((r) => setItems(r.items))
      .catch((e) => { setError(e.message); setItems([]); });
  }, []);

  if (items === null) return <div className="pf-panel"><SkeletonCards n={3} /></div>;

  if (items.length === 0 && !error) {
    return (
      <div className="pf-panel">
        <div className="pf-empty">
          <p className="pf-empty-big">No lookups yet</p>
          <p>Your identification history will appear here after your first photo ID.</p>
        </div>
      </div>
    );
  }

  const fmt = (ts) => {
    const d = new Date(ts);
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  };

  return (
    <div className="pf-panel">
      <h3 className="pf-section-title">
        Recent lookups <span className="pf-count">{items.length}</span>
      </h3>
      {error && <p className="pf-error">{error}</p>}
      <div className="pf-stack">
        {items.map((item, i) => (
          <div key={i} className="pf-card pf-history-row">
            <div className="pf-history-meta">
              <span className="pf-history-ts">{fmt(item.ts_utc)}</span>
              {item.category_hint && (
                <span className="pf-chip pf-chip-cat">{item.category_hint}</span>
              )}
            </div>
            <div className="pf-history-result">
              {item.top_brand ? (
                <>
                  <span className="pf-history-brand">{item.top_brand}</span>
                  {item.top_confidence != null && (
                    <span className="pf-history-conf">
                      {Math.round(item.top_confidence * 100)}%
                    </span>
                  )}
                </>
              ) : (
                <span className="pf-muted">No match</span>
              )}
              {item.candidate_count > 1 && (
                <span className="pf-history-more">+{item.candidate_count - 1} other</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SkeletonCards({ n = 2 }) {
  return (
    <div className="pf-stack">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="pf-skeleton" style={{ animationDelay: `${i * 100}ms` }} />
      ))}
    </div>
  );
}
