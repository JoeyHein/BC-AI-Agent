import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { emailAgentApi } from '../api/client'
import { formatDate, formatDateTime } from '../utils/datetime'

const TONE_OPTIONS = [
  'Friendly & casual',
  'Professional update',
  'Story-driven',
  'Motivational',
]

function WeeklyEmail() {
  const queryClient = useQueryClient()
  const [step, setStep] = useState('brief') // brief | preview | sent
  const [brief, setBrief] = useState({
    what_happened: '',
    coming_up: '',
    tone: 'Friendly & casual',
    promo_mention: '',
    subject_idea: '',
  })
  const [draft, setDraft] = useState(null)
  const [editedSubject, setEditedSubject] = useState('')
  const [editedPreheader, setEditedPreheader] = useState('')
  const [editedHtml, setEditedHtml] = useState('')
  const [editedText, setEditedText] = useState('')
  const [previewWidth, setPreviewWidth] = useState('desktop')
  const [showConfirm, setShowConfirm] = useState(false)
  const [sendResult, setSendResult] = useState(null)
  const [error, setError] = useState(null)
  const iframeRef = useRef(null)

  // Test send + media insertion
  const [testEmail, setTestEmail] = useState('')
  const [testNotice, setTestNotice] = useState(null)
  const [uploadingImage, setUploadingImage] = useState(false)
  const [showVideoModal, setShowVideoModal] = useState(false)
  const [videoUrl, setVideoUrl] = useState('')
  const htmlRef = useRef(null)
  const imageInputRef = useRef(null)

  // Audience count
  const { data: audienceData } = useQuery({
    queryKey: ['emailAgent', 'audience'],
    queryFn: async () => {
      const res = await emailAgentApi.getAudienceCount()
      return res.data
    },
    staleTime: 60000,
  })

  // Send history
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['emailAgent', 'history'],
    queryFn: async () => {
      const res = await emailAgentApi.getHistory()
      return res.data
    },
    staleTime: 30000,
  })

  // Generate mutation
  const generateMutation = useMutation({
    mutationFn: async (briefData) => {
      const res = await emailAgentApi.generate(briefData)
      return res.data
    },
    onSuccess: (data) => {
      if (data.success) {
        setDraft(data.draft)
        setEditedSubject(data.draft.subject)
        setEditedPreheader(data.draft.preheader)
        setEditedHtml(data.draft.body_html)
        setEditedText(data.draft.body_text)
        setStep('preview')
        setError(null)
      }
    },
    onError: (err) => {
      setError(err.response?.data?.detail || 'Failed to generate email. Please try again.')
    },
  })

  // Send mutation
  const sendMutation = useMutation({
    mutationFn: async (sendData) => {
      const res = await emailAgentApi.send(sendData)
      return res.data
    },
    onSuccess: (data) => {
      if (data.success) {
        setSendResult(data)
        setStep('sent')
        setShowConfirm(false)
        queryClient.invalidateQueries({ queryKey: ['emailAgent', 'history'] })
      }
    },
    onError: (err) => {
      setShowConfirm(false)
      setError(err.response?.data?.detail || 'Failed to send email.')
    },
  })

  // Test send mutation
  const testMutation = useMutation({
    mutationFn: async (data) => {
      const res = await emailAgentApi.sendTest(data)
      return res.data
    },
    onSuccess: (data) => {
      setTestNotice(data.message || `Test sent to ${data.test_email}`)
      setError(null)
    },
    onError: (err) => {
      setError(err.response?.data?.detail || 'Failed to send test email.')
    },
  })

  // Insert an HTML snippet at the cursor in the body textarea (or append).
  const insertIntoHtml = (snippet) => {
    const el = htmlRef.current
    if (el && typeof el.selectionStart === 'number') {
      const start = el.selectionStart
      const next = editedHtml.slice(0, start) + snippet + editedHtml.slice(el.selectionEnd)
      setEditedHtml(next)
    } else {
      setEditedHtml(editedHtml + snippet)
    }
  }

  const handleImageSelected = async (e) => {
    const file = e.target.files?.[0]
    if (e.target) e.target.value = '' // allow re-selecting the same file
    if (!file) return
    setUploadingImage(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('image', file)
      const res = await emailAgentApi.uploadImage(formData)
      const url = res.data?.url
      if (url) {
        insertIntoHtml(
          `\n<div style="padding:0 25px 20px;text-align:center;"><img src="${url}" alt="" style="max-width:100%;height:auto;border-radius:4px;" /></div>\n`
        )
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Image upload failed.')
    } finally {
      setUploadingImage(false)
    }
  }

  // Build a YouTube/Vimeo thumbnail URL when possible, so video links get a poster.
  const youtubeThumb = (url) => {
    const m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([\w-]{11})/)
    return m ? `https://img.youtube.com/vi/${m[1]}/hqdefault.jpg` : null
  }

  const handleInsertVideo = () => {
    const url = videoUrl.trim()
    if (!/^https?:\/\//i.test(url)) {
      setError('Enter a valid video URL (starting with http).')
      return
    }
    const thumb = youtubeThumb(url) || 'https://portal.opendc.ca/assets/opendc-logo.jpg'
    // Email clients can't play inline video — insert a clickable poster with a play overlay.
    const snippet =
      `\n<div style="padding:0 25px 20px;text-align:center;">` +
      `<a href="${url}" target="_blank" style="display:inline-block;position:relative;text-decoration:none;">` +
      `<img src="${thumb}" alt="Watch the video" style="max-width:100%;height:auto;border-radius:4px;display:block;" />` +
      `<span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(224,123,0,0.92);color:#ffffff;width:56px;height:56px;border-radius:50%;line-height:56px;font-size:22px;">&#9654;</span>` +
      `</a>` +
      `<p style="margin:8px 0 0;font-size:13px;"><a href="${url}" style="color:#E07B00;">Watch the video &rarr;</a></p>` +
      `</div>\n`
    insertIntoHtml(snippet)
    setVideoUrl('')
    setShowVideoModal(false)
    setError(null)
  }

  // Update iframe when HTML changes
  const updateIframe = useCallback(() => {
    if (iframeRef.current) {
      const doc = iframeRef.current.contentDocument
      if (doc) {
        doc.open()
        doc.write(editedHtml)
        doc.close()
      }
    }
  }, [editedHtml])

  useEffect(() => {
    updateIframe()
  }, [updateIframe])

  const handleGenerate = () => {
    if (!brief.what_happened.trim()) {
      setError('Please fill in what happened this week.')
      return
    }
    setError(null)
    generateMutation.mutate(brief)
  }

  const handleSend = () => {
    if (!editedSubject.trim()) {
      setError('Subject line cannot be empty.')
      return
    }
    setError(null)
    sendMutation.mutate({
      subject: editedSubject,
      preheader: editedPreheader,
      body_html: editedHtml,
      body_text: editedText,
      brief_summary: brief.what_happened.substring(0, 100),
    })
  }

  const handleStartNew = () => {
    setStep('brief')
    setBrief({ what_happened: '', coming_up: '', tone: 'Friendly & casual', promo_mention: '', subject_idea: '' })
    setDraft(null)
    setSendResult(null)
    setError(null)
  }

  const subscriberCount = audienceData?.count || 0
  const isConfigured = audienceData?.configured !== false

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Weekly Email</h1>
          <p className="mt-1 text-sm text-gray-500">
            Write and send your weekly update to the OPENDC client list
          </p>
        </div>
        {isConfigured && subscriberCount > 0 && (
          <div className="text-sm text-gray-500">
            <span className="font-medium text-gray-700">{subscriberCount.toLocaleString()}</span> subscribers
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex justify-between items-start">
            <p className="text-sm text-red-700">{error}</p>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 ml-4 text-lg leading-none">&times;</button>
          </div>
        </div>
      )}

      {/* Not configured warning */}
      {audienceData && !isConfigured && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800 font-medium">Mailchimp not configured</p>
          <p className="text-sm text-yellow-700 mt-1">
            Set MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, and MAILCHIMP_AUDIENCE_ID in your .env file.
            See MAILCHIMP_SETUP.md for instructions.
          </p>
        </div>
      )}

      {/* STEP 1: Brief Form */}
      {step === 'brief' && (
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Brief the AI</h2>
            <p className="text-sm text-gray-500 mt-1">Fill in a few fields and Claude will write the email in Joey's voice</p>
          </div>
          <div className="p-6 space-y-5">
            {/* What happened */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                What happened this week? <span className="text-red-500">*</span>
              </label>
              <textarea
                value={brief.what_happened}
                onChange={(e) => setBrief({ ...brief, what_happened: e.target.value })}
                rows={4}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Shipped a big commercial job in Lethbridge, got new Clopay stock in, trained two new installers..."
              />
            </div>

            {/* Coming up */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anything coming up?
              </label>
              <textarea
                value={brief.coming_up}
                onChange={(e) => setBrief({ ...brief, coming_up: e.target.value })}
                rows={3}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Spring rush starting, lead times tightening on steel doors..."
              />
            </div>

            {/* Tone */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Tone this week
              </label>
              <div className="flex flex-wrap gap-2">
                {TONE_OPTIONS.map((tone) => (
                  <button
                    key={tone}
                    onClick={() => setBrief({ ...brief, tone })}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                      brief.tone === tone
                        ? 'bg-odc-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {tone}
                  </button>
                ))}
              </div>
            </div>

            {/* Promo */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Any specific product or promo to mention?
              </label>
              <input
                type="text"
                value={brief.promo_mention}
                onChange={(e) => setBrief({ ...brief, promo_mention: e.target.value })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Optional — leave blank if nothing specific"
              />
            </div>

            {/* Subject idea */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email subject line idea
              </label>
              <input
                type="text"
                value={brief.subject_idea}
                onChange={(e) => setBrief({ ...brief, subject_idea: e.target.value })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Optional — Claude will generate one if left blank"
              />
            </div>

            {/* Generate button */}
            <div className="pt-2">
              <button
                onClick={handleGenerate}
                disabled={generateMutation.isPending || !brief.what_happened.trim()}
                className="inline-flex items-center px-5 py-2.5 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generateMutation.isPending ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating...
                  </>
                ) : (
                  'Generate Email'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 2: Preview / Edit */}
      {step === 'preview' && draft && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Edit panel */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-lg font-medium text-gray-900">Edit</h2>
                <div className="flex gap-2">
                  <button
                    onClick={() => setStep('brief')}
                    className="text-sm text-gray-500 hover:text-gray-700"
                  >
                    Edit Brief
                  </button>
                  <button
                    onClick={handleGenerate}
                    disabled={generateMutation.isPending}
                    className="text-sm text-odc-600 hover:text-odc-700 font-medium"
                  >
                    {generateMutation.isPending ? 'Regenerating...' : 'Regenerate'}
                  </button>
                </div>
              </div>
              <div className="p-6 space-y-4">
                {/* Subject */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subject line</label>
                  <input
                    type="text"
                    value={editedSubject}
                    onChange={(e) => setEditedSubject(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                  />
                </div>

                {/* Preheader */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Preheader text</label>
                  <input
                    type="text"
                    value={editedPreheader}
                    onChange={(e) => setEditedPreheader(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                  />
                </div>

                {/* HTML body */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-sm font-medium text-gray-700">Email body (HTML)</label>
                    <div className="flex items-center gap-2">
                      <input
                        ref={imageInputRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleImageSelected}
                      />
                      <button
                        type="button"
                        onClick={() => imageInputRef.current?.click()}
                        disabled={uploadingImage}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                      >
                        {uploadingImage ? 'Uploading…' : '+ Image'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowVideoModal(true)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border border-gray-300 text-gray-700 bg-white hover:bg-gray-50"
                      >
                        + Video
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-400 mb-1">Click into the body where you want media, then insert. Images host on Mailchimp's CDN.</p>
                  <textarea
                    ref={htmlRef}
                    value={editedHtml}
                    onChange={(e) => setEditedHtml(e.target.value)}
                    rows={16}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 font-mono text-xs"
                  />
                </div>

                {/* Internal notes */}
                {draft.internal_notes && (
                  <div className="bg-gray-50 rounded-md p-3">
                    <p className="text-xs font-medium text-gray-500 mb-1">AI Notes</p>
                    <p className="text-sm text-gray-600">{draft.internal_notes}</p>
                  </div>
                )}
              </div>
            </div>

            {/* Right: Preview panel */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-lg font-medium text-gray-900">Preview</h2>
                <div className="flex bg-gray-100 rounded-md p-0.5">
                  <button
                    onClick={() => setPreviewWidth('desktop')}
                    className={`px-3 py-1 text-xs font-medium rounded ${
                      previewWidth === 'desktop' ? 'bg-white shadow text-gray-900' : 'text-gray-500'
                    }`}
                  >
                    Desktop
                  </button>
                  <button
                    onClick={() => setPreviewWidth('mobile')}
                    className={`px-3 py-1 text-xs font-medium rounded ${
                      previewWidth === 'mobile' ? 'bg-white shadow text-gray-900' : 'text-gray-500'
                    }`}
                  >
                    Mobile
                  </button>
                </div>
              </div>

              {/* Inbox simulation header */}
              <div className="bg-gray-50 px-6 py-3 border-b border-gray-100">
                <p className="text-sm font-medium text-gray-900 truncate">{editedSubject || '(No subject)'}</p>
                <p className="text-xs text-gray-500 truncate mt-0.5">{editedPreheader}</p>
              </div>

              {/* Email preview iframe */}
              <div className="bg-gray-100 p-4 flex justify-center" style={{ minHeight: '500px' }}>
                <div
                  className="bg-white shadow-lg rounded-sm overflow-hidden transition-all duration-200"
                  style={{ width: previewWidth === 'desktop' ? '600px' : '375px', maxWidth: '100%' }}
                >
                  <iframe
                    ref={iframeRef}
                    title="Email Preview"
                    style={{ width: '100%', minHeight: '480px', border: 'none' }}
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Test send row */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-6 py-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-blue-900">Send yourself a test first</p>
                <p className="text-xs text-blue-700 mt-0.5">Check branding and media in a real inbox before the full send. Doesn't touch your list.</p>
                {testNotice && <p className="text-xs text-green-700 mt-1 font-medium">✓ {testNotice}</p>}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="email"
                  value={testEmail}
                  onChange={(e) => setTestEmail(e.target.value)}
                  placeholder="joey@opendc.ca"
                  className="rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm w-52"
                />
                <button
                  onClick={() => {
                    setTestNotice(null)
                    testMutation.mutate({
                      subject: editedSubject,
                      preheader: editedPreheader,
                      body_html: editedHtml,
                      body_text: editedText,
                      test_email: testEmail || undefined,
                    })
                  }}
                  disabled={testMutation.isPending || !editedSubject.trim() || !isConfigured}
                  className="inline-flex items-center px-4 py-2 border border-blue-300 text-sm font-medium rounded-md text-blue-800 bg-white hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  {testMutation.isPending ? 'Sending…' : 'Send Test'}
                </button>
              </div>
            </div>
          </div>

          {/* Send button row */}
          <div className="bg-white shadow rounded-lg px-6 py-4 flex items-center justify-between">
            <button
              onClick={() => setStep('brief')}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Back to Brief
            </button>
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(editedHtml)
                  setError(null)
                }}
                className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
              >
                Copy HTML
              </button>
              <button
                onClick={() => setShowConfirm(true)}
                disabled={!editedSubject.trim() || !isConfigured}
                className="inline-flex items-center px-5 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Send via Mailchimp
              </button>
            </div>
          </div>
        </>
      )}

      {/* Insert video modal */}
      {showVideoModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4">
            <div className="fixed inset-0 bg-gray-500 bg-opacity-75" onClick={() => setShowVideoModal(false)} />
            <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Insert Video</h3>
              <p className="text-sm text-gray-500 mb-4">
                Email can't play video inline, so we insert a clickable thumbnail that links to it.
                Paste a YouTube/Vimeo or hosted video link — YouTube thumbnails are pulled in automatically.
              </p>
              <input
                type="url"
                value={videoUrl}
                onChange={(e) => setVideoUrl(e.target.value)}
                placeholder="https://youtu.be/…"
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 text-sm mb-4"
                autoFocus
              />
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => { setShowVideoModal(false); setVideoUrl('') }}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleInsertVideo}
                  className="px-4 py-2 text-sm font-medium text-white bg-odc-600 border border-transparent rounded-md hover:bg-odc-700"
                >
                  Insert
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* STEP 3: Success */}
      {step === 'sent' && sendResult && (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
            <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Email Sent!</h2>
          <p className="text-gray-600 mb-6">
            Your weekly update has been sent to{' '}
            <span className="font-medium">{sendResult.recipient_count?.toLocaleString()}</span> subscribers.
          </p>
          <div className="bg-gray-50 rounded-lg p-4 max-w-sm mx-auto text-left text-sm space-y-1 mb-6">
            <p><span className="text-gray-500">Campaign ID:</span> <span className="font-mono text-gray-700">{sendResult.campaign_id}</span></p>
            <p><span className="text-gray-500">Sent at:</span> <span className="text-gray-700">{formatDateTime(sendResult.sent_at)}</span></p>
          </div>
          <button
            onClick={handleStartNew}
            className="inline-flex items-center px-5 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
          >
            Write Another Email
          </button>
        </div>
      )}

      {/* Send confirmation dialog */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4">
            <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={() => setShowConfirm(false)} />
            <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-sm w-full">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Confirm Send</h3>
              <p className="text-sm text-gray-600 mb-4">
                Send this email to{' '}
                <span className="font-medium">{subscriberCount.toLocaleString()}</span> subscribers?
              </p>
              <p className="text-sm text-gray-500 mb-6 truncate">
                Subject: <span className="font-medium text-gray-700">{editedSubject}</span>
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowConfirm(false)}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSend}
                  disabled={sendMutation.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-odc-600 border border-transparent rounded-md hover:bg-odc-700 disabled:opacity-50"
                >
                  {sendMutation.isPending ? 'Sending...' : 'Send Now'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Past Emails */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Past Emails</h2>
        </div>
        <div className="overflow-x-auto">
          {historyLoading ? (
            <div className="p-6 text-center text-sm text-gray-500">Loading history...</div>
          ) : !historyData?.campaigns?.length ? (
            <div className="p-6 text-center text-sm text-gray-500">No emails sent yet</div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Subject</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Recipients</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Mailchimp</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {historyData.campaigns.map((c) => (
                  <tr key={c.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {c.sent_at ? formatDate(c.sent_at) : '—'}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900 max-w-xs truncate">{c.subject}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{c.recipient_count?.toLocaleString()}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {c.mailchimp_campaign_id && (
                        <a
                          href={`https://${audienceData?.audience_name ? '' : ''}admin.mailchimp.com/reports/summary?id=${c.mailchimp_campaign_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-odc-600 hover:text-odc-700"
                        >
                          View Report
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default WeeklyEmail
