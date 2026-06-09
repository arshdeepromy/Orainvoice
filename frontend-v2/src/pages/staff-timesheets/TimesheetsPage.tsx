import { useState } from 'react'
import ClockedInTab from './ClockedInTab'
import TimesheetsTab from './TimesheetsTab'

const TABS = ['Clocked In', 'Timesheets'] as const

export default function TimesheetsPage() {
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>('Clocked In')

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-text">Staff Timesheets</h1>
      </div>

      {/* Tab switcher */}
      <div className="border-b border-border">
        <nav className="flex gap-4">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-2 text-sm font-medium transition-colors ${
                activeTab === tab
                  ? 'border-b-2 border-accent text-accent'
                  : 'text-muted hover:text-text'
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'Clocked In' && <ClockedInTab />}
      {activeTab === 'Timesheets' && <TimesheetsTab />}
    </div>
  )
}
