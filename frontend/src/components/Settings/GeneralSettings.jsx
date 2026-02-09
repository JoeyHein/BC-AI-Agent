function GeneralSettings() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-gray-900">General Settings</h2>
        <p className="text-sm text-gray-500">
          Configure general application preferences
        </p>
      </div>

      {/* Placeholder content */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
        <svg
          className="mx-auto h-12 w-12 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1}
            d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
          />
        </svg>
        <h3 className="mt-4 text-sm font-medium text-gray-900">Coming Soon</h3>
        <p className="mt-2 text-sm text-gray-500">
          General settings such as company information, default values, and preferences
          will be available here in a future update.
        </p>
      </div>

      {/* Future settings preview */}
      <div className="border-t border-gray-200 pt-6">
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          Planned Settings
        </h3>
        <ul className="space-y-3">
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Company Information
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Default Track Sizes
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Hardware Preferences
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            Pricing Rules & Markup
          </li>
          <li className="flex items-center text-sm text-gray-600">
            <span className="w-2 h-2 bg-gray-300 rounded-full mr-3"></span>
            User Management (Admin)
          </li>
        </ul>
      </div>
    </div>
  )
}

export default GeneralSettings
