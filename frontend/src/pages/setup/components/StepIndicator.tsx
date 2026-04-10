export interface StepInfo {
  label: string
  completed: boolean
  skipped: boolean
}

interface StepIndicatorProps {
  steps: StepInfo[]
  currentStep: number
}

export function StepIndicator({ steps, currentStep }: StepIndicatorProps) {
  const totalSteps = steps.length

  return (
    <nav aria-label="Setup wizard progress" className="mb-8">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">
          Step {currentStep + 1} of {totalSteps}
        </span>
        <span className="text-sm text-gray-500">{steps[currentStep]?.label}</span>
      </div>
      <div
        className="flex gap-1.5"
        role="progressbar"
        aria-valuenow={currentStep + 1}
        aria-valuemin={1}
        aria-valuemax={totalSteps}
        aria-label={`Step ${currentStep + 1} of ${totalSteps}: ${steps[currentStep]?.label}`}
      >
        {steps.map((step, i) => {
          let colorClass = 'bg-gray-200'
          if (i < currentStep || step.completed) {
            colorClass = 'bg-blue-600'
          } else if (i === currentStep) {
            colorClass = 'bg-blue-400'
          } else if (step.skipped) {
            colorClass = 'bg-amber-300'
          }

          return (
            <div
              key={i}
              className={`h-2 flex-1 rounded-full transition-colors ${colorClass}`}
              title={`${step.label}${step.completed ? ' (completed)' : step.skipped ? ' (skipped)' : ''}`}
            />
          )
        })}
      </div>
      {/* Step dots for larger screens */}
      <ol className="hidden sm:flex justify-between mt-3">
        {steps.map((step, i) => (
          <li
            key={i}
            className={`text-xs text-center flex-1 ${
              i === currentStep
                ? 'text-blue-600 font-medium'
                : i < currentStep || step.completed
                  ? 'text-gray-600'
                  : 'text-gray-400'
            }`}
          >
            {step.label}
          </li>
        ))}
      </ol>
    </nav>
  )
}
