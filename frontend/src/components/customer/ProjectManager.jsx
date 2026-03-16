import { useState, useEffect } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../../api/customerClient'
import { useCustomerAuth } from '../../contexts/CustomerAuthContext'
import InstallReferralForm from './InstallReferralForm'
import { InstallReferralList } from './InstallReferralStatus'

// ─── Status badge helpers ───────────────────────────────────────────────────

const projectStatusColors = {
  active: 'bg-green-100 text-green-800',
  complete: 'bg-blue-100 text-blue-800',
  cancelled: 'bg-gray-100 text-gray-800',
}

const projectStatusLabels = {
  active: 'Active',
  complete: 'Complete',
  cancelled: 'Cancelled',
}

const lotStatusColors = {
  quoted: 'bg-gray-100 text-gray-800',
  released: 'bg-blue-100 text-blue-800',
  ordered: 'bg-amber-100 text-amber-800',
  shipped: 'bg-purple-100 text-purple-800',
  complete: 'bg-green-100 text-green-800',
}

const lotStatusLabels = {
  quoted: 'Quoted',
  released: 'Released',
  ordered: 'Ordered',
  shipped: 'Shipped',
  complete: 'Complete',
}

function StatusBadge({ status, colorMap, labelMap }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorMap[status] || 'bg-gray-100 text-gray-800'}`}>
      {labelMap[status] || status}
    </span>
  )
}

function BillingBadge({ mode }) {
  const color = mode === 'staged' ? 'bg-indigo-100 text-indigo-800' : 'bg-teal-100 text-teal-800'
  const label = mode === 'staged' ? 'Staged' : 'Full'
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {label}
    </span>
  )
}

// ─── Main component (switches between list and detail based on route) ───────

function ProjectManager() {
  const { id } = useParams()

  if (id) {
    return <ProjectDetail projectId={id} />
  }
  return <ProjectList />
}

// ─── Project List View ──────────────────────────────────────────────────────

function ProjectList() {
  const [showNewModal, setShowNewModal] = useState(false)
  const queryClient = useQueryClient()

  const { data: projects, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: async () => {
      const response = await projectsApi.list()
      return response.data
    }
  })

  const createMutation = useMutation({
    mutationFn: (data) => projectsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setShowNewModal(false)
    }
  })

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load projects. Please try again.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">My Projects</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your building projects and lot releases
          </p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500"
        >
          <PlusIcon className="h-5 w-5 mr-2" />
          New Project
        </button>
      </div>

      {/* Projects grid */}
      {(!projects || projects.length === 0) ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <ProjectIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-2 text-sm font-medium text-gray-900">No projects</h3>
          <p className="mt-1 text-sm text-gray-500">
            Get started by creating a new project.
          </p>
          <div className="mt-6">
            <button
              onClick={() => setShowNewModal(true)}
              className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
            >
              <PlusIcon className="-ml-1 mr-2 h-5 w-5" />
              New Project
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => {
            const totalLots = project.lot_count || 0
            const releasedLots = project.released_lot_count || 0
            return (
              <Link
                key={project.id}
                to={`${project.id}`}
                className="bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-shadow p-5 block"
              >
                <div className="flex items-start justify-between">
                  <h3 className="text-base font-semibold text-gray-900 truncate pr-2">
                    {project.name}
                  </h3>
                  <StatusBadge
                    status={project.status}
                    colorMap={projectStatusColors}
                    labelMap={projectStatusLabels}
                  />
                </div>

                <div className="mt-3 flex items-center space-x-2">
                  <BillingBadge mode={project.billing_mode} />
                  <span className="text-xs text-gray-500">
                    {totalLots} lot{totalLots !== 1 ? 's' : ''}
                  </span>
                </div>

                {totalLots > 0 && (
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                      <span>{releasedLots} of {totalLots} lots released</span>
                      <span>{totalLots > 0 ? Math.round((releasedLots / totalLots) * 100) : 0}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5">
                      <div
                        className="bg-odc-600 h-1.5 rounded-full transition-all"
                        style={{ width: `${totalLots > 0 ? (releasedLots / totalLots) * 100 : 0}%` }}
                      ></div>
                    </div>
                  </div>
                )}

                <p className="mt-3 text-xs text-gray-400">
                  Created {new Date(project.created_at).toLocaleDateString()}
                </p>
              </Link>
            )
          })}
        </div>
      )}

      {/* New Project Modal */}
      {showNewModal && (
        <NewProjectModal
          onClose={() => setShowNewModal(false)}
          onSubmit={(data) => createMutation.mutate(data)}
          isLoading={createMutation.isPending}
          error={createMutation.error?.response?.data?.detail}
        />
      )}
    </div>
  )
}

// ─── New Project Modal ──────────────────────────────────────────────────────

function NewProjectModal({ onClose, onSubmit, isLoading, error }) {
  const [name, setName] = useState('')
  const [billingMode, setBillingMode] = useState('full')
  const [notes, setNotes] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit({ name, billing_mode: billingMode, notes: notes || undefined })
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>
        <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6 z-10">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-gray-900">New Project</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <XIcon className="h-5 w-5" />
            </button>
          </div>

          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 rounded p-3">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Project Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="e.g. Maple Ridge Phase 3"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Billing Mode</label>
              <select
                value={billingMode}
                onChange={(e) => setBillingMode(e.target.value)}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
              >
                <option value="full">Full - Release all lots at once</option>
                <option value="staged">Staged - Release lots in stages</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Notes</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="Optional project notes..."
              />
            </div>

            <div className="flex justify-end space-x-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !name.trim()}
                className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
              >
                {isLoading ? 'Creating...' : 'Create Project'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// ─── Project Detail View ────────────────────────────────────────────────────

function ProjectDetail({ projectId }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showAddLots, setShowAddLots] = useState(false)
  const [editingLot, setEditingLot] = useState(null)
  const [showReleaseConfirm, setShowReleaseConfirm] = useState(null) // null | 'all' | stage number

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', projectId],
    queryFn: async () => {
      const response = await projectsApi.get(projectId)
      return response.data
    }
  })

  const { data: invoiceSummary } = useQuery({
    queryKey: ['project-invoices', projectId],
    queryFn: async () => {
      const response = await projectsApi.getInvoiceSummary(projectId)
      return response.data
    },
    enabled: !!project?.lots?.some(l => ['ordered', 'shipped', 'complete'].includes(l.status))
  })

  const updateProjectMutation = useMutation({
    mutationFn: (data) => projectsApi.update(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    }
  })

  const addLotsMutation = useMutation({
    mutationFn: (lots) => projectsApi.addLots(projectId, lots),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setShowAddLots(false)
    }
  })

  const updateLotMutation = useMutation({
    mutationFn: ({ lotId, data }) => projectsApi.updateLot(projectId, lotId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      setEditingLot(null)
    }
  })

  const deleteLotMutation = useMutation({
    mutationFn: (lotId) => projectsApi.deleteLot(projectId, lotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    }
  })

  const releaseMutation = useMutation({
    mutationFn: (data) => projectsApi.release(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setShowReleaseConfirm(null)
    }
  })

  const handleDeleteLot = (lotId, address) => {
    if (window.confirm(`Delete lot "${address || lotId}"? This cannot be undone.`)) {
      deleteLotMutation.mutate(lotId)
    }
  }

  const handleRelease = (stage) => {
    setShowReleaseConfirm(stage)
  }

  const confirmRelease = () => {
    const data = showReleaseConfirm === 'all' ? {} : { stage: showReleaseConfirm }
    releaseMutation.mutate(data)
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-odc-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <p className="text-red-700">Failed to load project. Please try again.</p>
      </div>
    )
  }

  if (!project) return null

  const lots = project.lots || []
  const quotedLots = lots.filter(l => l.status === 'quoted')
  const isStaged = project.billing_mode === 'staged'

  // Group lots by stage for staged mode
  const stageGroups = {}
  if (isStaged) {
    lots.forEach(lot => {
      const stage = lot.stage || 1
      if (!stageGroups[stage]) stageGroups[stage] = []
      stageGroups[stage].push(lot)
    })
  }

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        to="/projects"
        className="inline-flex items-center text-sm text-odc-600 hover:text-odc-500"
      >
        <ArrowLeftIcon className="h-4 w-4 mr-1" />
        Back to Projects
      </Link>

      {/* Project header */}
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
            <div className="mt-2 flex items-center space-x-3">
              <StatusBadge status={project.status} colorMap={projectStatusColors} labelMap={projectStatusLabels} />
              <BillingBadge mode={project.billing_mode} />
              {project.bc_quote_number && (
                <span className="text-sm text-gray-500">
                  BC Quote: {project.bc_quote_number}
                </span>
              )}
            </div>
            {project.notes && (
              <p className="mt-2 text-sm text-gray-500">{project.notes}</p>
            )}
          </div>
          <div className="text-sm text-gray-400">
            Created {new Date(project.created_at).toLocaleDateString()}
          </div>
        </div>
      </div>

      {/* Lots section */}
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-medium text-gray-900">
            Lots ({lots.length})
          </h2>
          <button
            onClick={() => setShowAddLots(true)}
            className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
          >
            <PlusIcon className="h-4 w-4 mr-1" />
            Add Lots
          </button>
        </div>

        {lots.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-500">No lots added yet. Add lots to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Lot #</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Address</th>
                  {isStaged && (
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stage</th>
                  )}
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Door Spec</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {lots.map((lot) => (
                  <tr key={lot.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {lot.lot_number}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                      {lot.address || '-'}
                    </td>
                    {isStaged && (
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                        {lot.stage || '-'}
                      </td>
                    )}
                    <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">
                      {lot.door_spec ? (typeof lot.door_spec === 'string' ? lot.door_spec : JSON.stringify(lot.door_spec)) : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <StatusBadge status={lot.status} colorMap={lotStatusColors} labelMap={lotStatusLabels} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm">
                      {lot.status === 'quoted' && (
                        <div className="flex justify-end space-x-2">
                          <button
                            onClick={() => setEditingLot(lot)}
                            className="text-odc-600 hover:text-odc-800 font-medium"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDeleteLot(lot.id, lot.address)}
                            disabled={deleteLotMutation.isPending}
                            className="text-red-600 hover:text-red-800 font-medium"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Release section */}
      {quotedLots.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Release Lots</h2>

          {!isStaged ? (
            /* Full mode */
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-600">
                {quotedLots.length} lot{quotedLots.length !== 1 ? 's' : ''} ready to release.
              </p>
              <button
                onClick={() => handleRelease('all')}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
              >
                Release All Lots
              </button>
            </div>
          ) : (
            /* Staged mode */
            <div className="space-y-3">
              {Object.keys(stageGroups).sort((a, b) => a - b).map(stage => {
                const stageLots = stageGroups[stage]
                const stageQuotedCount = stageLots.filter(l => l.status === 'quoted').length
                return (
                  <div key={stage} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                    <div>
                      <span className="text-sm font-medium text-gray-900">Stage {stage}</span>
                      <span className="ml-2 text-sm text-gray-500">
                        {stageLots.length} lot{stageLots.length !== 1 ? 's' : ''}
                        {stageQuotedCount > 0 && stageQuotedCount < stageLots.length && (
                          <> ({stageQuotedCount} quoted)</>
                        )}
                      </span>
                    </div>
                    {stageQuotedCount > 0 && (
                      <button
                        onClick={() => handleRelease(Number(stage))}
                        className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-odc-600 hover:bg-odc-700"
                      >
                        Release Stage {stage}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Invoice Summary section */}
      {invoiceSummary && invoiceSummary.invoices && invoiceSummary.invoices.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Invoice Summary</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {isStaged && (
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stage</th>
                  )}
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">BC Invoice #</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Amount</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {invoiceSummary.invoices.map((inv, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    {isStaged && (
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">{inv.stage || '-'}</td>
                    )}
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{inv.bc_invoice_number || '-'}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700 text-right">
                      {inv.total_amount != null ? `$${Number(inv.total_amount).toLocaleString('en-US', { minimumFractionDigits: 2 })} CAD` : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
              {invoiceSummary.grand_total != null && (
                <tfoot>
                  <tr className="bg-gray-50">
                    <td colSpan={isStaged ? 2 : 1} className="px-6 py-3 text-sm font-medium text-gray-900 text-right">Total</td>
                    <td className="px-6 py-3 text-sm font-bold text-gray-900 text-right">
                      ${Number(invoiceSummary.grand_total).toLocaleString('en-US', { minimumFractionDigits: 2 })} CAD
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      {/* Install Referral section */}
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Installation Service</h2>
        <p className="text-sm text-gray-500 mb-4">
          Need installation? We can connect you with a qualified installer for this project.
        </p>
        <InstallReferralForm
          orderRef={project.bc_quote_number || project.name}
          lotAddress={lots.length === 1 ? lots[0].address : ''}
          compact
        />
      </div>

      {/* Existing install referrals */}
      <InstallReferralList />

      {/* Add Lots Modal */}
      {showAddLots && (
        <AddLotsModal
          isStaged={isStaged}
          onClose={() => setShowAddLots(false)}
          onSubmit={(lots) => addLotsMutation.mutate(lots)}
          isLoading={addLotsMutation.isPending}
          error={addLotsMutation.error?.response?.data?.detail}
        />
      )}

      {/* Edit Lot Modal */}
      {editingLot && (
        <EditLotModal
          lot={editingLot}
          isStaged={isStaged}
          onClose={() => setEditingLot(null)}
          onSubmit={(data) => updateLotMutation.mutate({ lotId: editingLot.id, data })}
          isLoading={updateLotMutation.isPending}
          error={updateLotMutation.error?.response?.data?.detail}
        />
      )}

      {/* Release Confirmation Dialog */}
      {showReleaseConfirm !== null && (
        <ConfirmDialog
          title="Confirm Release"
          message={
            showReleaseConfirm === 'all'
              ? `Release all ${quotedLots.length} quoted lot${quotedLots.length !== 1 ? 's' : ''}? This will submit them for processing and cannot be undone.`
              : `Release all quoted lots in Stage ${showReleaseConfirm}? This will submit them for processing and cannot be undone.`
          }
          confirmLabel={releaseMutation.isPending ? 'Releasing...' : 'Release'}
          onConfirm={confirmRelease}
          onCancel={() => setShowReleaseConfirm(null)}
          isLoading={releaseMutation.isPending}
        />
      )}
    </div>
  )
}

// ─── Add Lots Modal ─────────────────────────────────────────────────────────

function AddLotsModal({ isStaged, onClose, onSubmit, isLoading, error }) {
  const [rows, setRows] = useState([{ lot_number: '', address: '', stage: '1', door_spec: '' }])

  const addRow = () => {
    setRows([...rows, { lot_number: '', address: '', stage: '1', door_spec: '' }])
  }

  const removeRow = (index) => {
    if (rows.length > 1) {
      setRows(rows.filter((_, i) => i !== index))
    }
  }

  const updateRow = (index, field, value) => {
    const updated = [...rows]
    updated[index] = { ...updated[index], [field]: value }
    setRows(updated)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const lots = rows
      .filter(r => r.lot_number.trim())
      .map(r => ({
        lot_number: r.lot_number.trim(),
        address: r.address.trim() || undefined,
        stage: isStaged ? (parseInt(r.stage) || 1) : undefined,
        door_spec: r.door_spec.trim() || undefined,
      }))
    if (lots.length === 0) return
    onSubmit(lots)
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>
        <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 z-10 max-h-[80vh] overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-gray-900">Add Lots</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <XIcon className="h-5 w-5" />
            </button>
          </div>

          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 rounded p-3">
              <p className="text-sm text-red-700">{typeof error === 'string' ? error : JSON.stringify(error)}</p>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="space-y-3">
              {rows.map((row, index) => (
                <div key={index} className="flex items-start space-x-2 p-3 bg-gray-50 rounded-md">
                  <div className="flex-1 grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium text-gray-600">Lot # *</label>
                      <input
                        type="text"
                        value={row.lot_number}
                        onChange={(e) => updateRow(index, 'lot_number', e.target.value)}
                        required
                        className="mt-0.5 block w-full border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        placeholder="e.g. 1"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600">Address</label>
                      <input
                        type="text"
                        value={row.address}
                        onChange={(e) => updateRow(index, 'address', e.target.value)}
                        className="mt-0.5 block w-full border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        placeholder="e.g. 123 Main St"
                      />
                    </div>
                    {isStaged && (
                      <div>
                        <label className="block text-xs font-medium text-gray-600">Stage</label>
                        <input
                          type="number"
                          min="1"
                          value={row.stage}
                          onChange={(e) => updateRow(index, 'stage', e.target.value)}
                          className="mt-0.5 block w-full border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        />
                      </div>
                    )}
                    <div className={isStaged ? '' : 'col-span-2'}>
                      <label className="block text-xs font-medium text-gray-600">Door Spec</label>
                      <input
                        type="text"
                        value={row.door_spec}
                        onChange={(e) => updateRow(index, 'door_spec', e.target.value)}
                        className="mt-0.5 block w-full border border-gray-300 rounded-md shadow-sm py-1.5 px-2 text-sm focus:outline-none focus:ring-odc-500 focus:border-odc-500"
                        placeholder="e.g. 9x7 T100 White"
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRow(index)}
                    disabled={rows.length === 1}
                    className="mt-5 text-gray-400 hover:text-red-500 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <XIcon className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={addRow}
              className="mt-3 inline-flex items-center text-sm text-odc-600 hover:text-odc-700 font-medium"
            >
              <PlusIcon className="h-4 w-4 mr-1" />
              Add another lot
            </button>

            <div className="flex justify-end space-x-3 mt-6 pt-4 border-t border-gray-200">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !rows.some(r => r.lot_number.trim())}
                className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
              >
                {isLoading ? 'Adding...' : `Add ${rows.filter(r => r.lot_number.trim()).length} Lot${rows.filter(r => r.lot_number.trim()).length !== 1 ? 's' : ''}`}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// ─── Edit Lot Modal ─────────────────────────────────────────────────────────

function EditLotModal({ lot, isStaged, onClose, onSubmit, isLoading, error }) {
  const [lotNumber, setLotNumber] = useState(lot.lot_number || '')
  const [address, setAddress] = useState(lot.address || '')
  const [stage, setStage] = useState(String(lot.stage || 1))
  const [doorSpec, setDoorSpec] = useState(
    lot.door_spec ? (typeof lot.door_spec === 'string' ? lot.door_spec : JSON.stringify(lot.door_spec)) : ''
  )

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit({
      lot_number: lotNumber.trim(),
      address: address.trim() || undefined,
      stage: isStaged ? (parseInt(stage) || 1) : undefined,
      door_spec: doorSpec.trim() || undefined,
    })
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>
        <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6 z-10">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-gray-900">Edit Lot</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <XIcon className="h-5 w-5" />
            </button>
          </div>

          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 rounded p-3">
              <p className="text-sm text-red-700">{typeof error === 'string' ? error : JSON.stringify(error)}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Lot # <span className="text-red-500">*</span></label>
              <input
                type="text"
                value={lotNumber}
                onChange={(e) => setLotNumber(e.target.value)}
                required
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Address</label>
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
              />
            </div>
            {isStaged && (
              <div>
                <label className="block text-sm font-medium text-gray-700">Stage</label>
                <input
                  type="number"
                  min="1"
                  value={stage}
                  onChange={(e) => setStage(e.target.value)}
                  className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                />
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700">Door Spec</label>
              <input
                type="text"
                value={doorSpec}
                onChange={(e) => setDoorSpec(e.target.value)}
                className="mt-1 block w-full border border-gray-300 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-odc-500 focus:border-odc-500 sm:text-sm"
                placeholder="e.g. 9x7 T100 White"
              />
            </div>

            <div className="flex justify-end space-x-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || !lotNumber.trim()}
                className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
              >
                {isLoading ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// ─── Confirm Dialog ─────────────────────────────────────────────────────────

function ConfirmDialog({ title, message, confirmLabel, onConfirm, onCancel, isLoading }) {
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onCancel}></div>
        <div className="relative bg-white rounded-lg shadow-xl max-w-sm w-full p-6 z-10">
          <h3 className="text-lg font-medium text-gray-900">{title}</h3>
          <p className="mt-2 text-sm text-gray-600">{message}</p>
          <div className="mt-5 flex justify-end space-x-3">
            <button
              onClick={onCancel}
              disabled={isLoading}
              className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isLoading}
              className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Icon Components ────────────────────────────────────────────────────────

function PlusIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
    </svg>
  )
}

function ProjectIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  )
}

function ArrowLeftIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
    </svg>
  )
}

function XIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

export default ProjectManager
