import { useEffect, useState } from 'react'
import SpringInventorySettings from './SpringInventorySettings'
import GeneralSettings from './GeneralSettings'
import PricingSettings from './PricingSettings'
import TravelDistanceSettings from './TravelDistanceSettings'
import InstallPricingSettings from './InstallPricingSettings'
import CatalogBuilder from './CatalogBuilder'
import InventoryDashboard from '../InventoryAgent/InventoryDashboard'
import POAgentDashboard from '../POAgent/POAgentDashboard'
import ServiceKeysSettings from './ServiceKeysSettings'
import ExternalKeysSettings from './ExternalKeysSettings'
import UsersSettings from './UsersSettings'
import { useAuth } from '../../contexts/AuthContext'

const TAB_DEFS = [
  { id: 'springs', name: 'Spring Inventory', icon: 'cog', view: 'settings.view', edit: 'settings.edit' },
  { id: 'pricing', name: 'Pricing', icon: 'currency', view: 'pricing.edit', edit: 'pricing.edit' },
  { id: 'install-pricing', name: 'Install Pricing', icon: 'currency', view: 'pricing.edit', edit: 'pricing.edit' },
  { id: 'travel', name: 'Travel Distances', icon: 'currency', view: 'settings.view', edit: 'settings.edit' },
  { id: 'catalog', name: 'Catalog Builder', icon: 'cog', view: 'inventory.view', edit: 'inventory.edit' },
  { id: 'inventory', name: 'Inventory Agent', icon: 'adjustments', view: 'inventory.view', edit: 'inventory.edit' },
  { id: 'po-agent', name: 'PO Agent', icon: 'currency', view: 'purchase_orders.view', edit: 'purchase_orders.edit' },
  { id: 'email', name: 'Email', icon: 'envelope', view: 'settings.view', edit: 'settings.edit' },
  { id: 'general', name: 'General', icon: 'adjustments', view: 'settings.view', edit: 'settings.edit' },
  { id: 'users', name: 'Users', icon: 'adjustments', view: 'users.view', edit: 'users.manage' },
  { id: 'service-keys', name: 'Service keys', icon: 'adjustments', view: 'users.manage', edit: 'users.manage' },
  { id: 'external-keys', name: 'External API keys', icon: 'adjustments', view: 'users.manage', edit: 'users.manage' },
]

function SettingsPage() {
  const { can } = useAuth()
  const tabs = TAB_DEFS.filter((tab) => can(tab.view))
  const [activeTab, setActiveTab] = useState(tabs[0]?.id || 'springs')
  useEffect(() => {
    if (tabs.length && !tabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(tabs[0].id)
    }
  }, [tabs, activeTab])
  const current = tabs.find((tab) => tab.id === activeTab) || tabs[0]
  const readOnly = current && !can(current.edit)

  const getTabIcon = (iconName) => {
    switch (iconName) {
      case 'cog':
        return (
          <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        )
      case 'envelope':
        return (
          <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        )
      case 'currency':
        return (
          <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        )
      case 'adjustments':
        return (
          <svg className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
          </svg>
        )
      default:
        return null
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage application settings and preferences
        </p>
        {readOnly && (
          <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
            This screen is view-only for your login. Saving is refused until an owner grants edit access.
          </p>
        )}
      </div>

      {/* Tab Navigation and Content */}
      <div className="bg-white shadow rounded-lg">
        <div className="border-b border-gray-200">
          <nav className="flex flex-wrap gap-x-6 px-6" aria-label="Tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  py-4 px-1 inline-flex items-center whitespace-nowrap border-b-2 font-medium text-sm
                  ${activeTab === tab.id
                    ? 'border-odc-500 text-odc-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }
                `}
              >
                {getTabIcon(tab.icon)}
                {tab.name}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {tabs.length === 0 && (
            <p className="text-sm text-gray-500">Your login does not include a settings screen.</p>
          )}
          {activeTab === 'springs' && <SpringInventorySettings />}
          {activeTab === 'pricing' && <PricingSettings />}
          {activeTab === 'install-pricing' && <InstallPricingSettings />}
          {activeTab === 'travel' && <TravelDistanceSettings />}
          {activeTab === 'catalog' && <CatalogBuilder />}
          {activeTab === 'inventory' && <InventoryDashboard />}
          {activeTab === 'po-agent' && <POAgentDashboard />}
          {activeTab === 'email' && <EmailSettingsTab />}
          {activeTab === 'general' && <GeneralSettings />}
          {activeTab === 'users' && <UsersSettings />}
          {activeTab === 'service-keys' && <ServiceKeysSettings />}
          {activeTab === 'external-keys' && <ExternalKeysSettings />}
        </div>
      </div>
    </div>
  )
}

// Email Settings Tab - redirects to existing EmailSettings or shows inline
function EmailSettingsTab() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-medium text-gray-900">Email Settings</h2>
        <p className="text-sm text-gray-500">
          Configure email connections and monitoring
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800">Email Configuration</h3>
            <p className="mt-2 text-sm text-blue-700">
              Email settings are managed separately. Use the dedicated email settings page for full functionality.
            </p>
            <div className="mt-3">
              <a
                href="/settings/email"
                className="text-sm font-medium text-blue-600 hover:text-blue-500"
              >
                Go to Email Settings →
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
