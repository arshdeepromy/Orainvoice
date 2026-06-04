import { useState } from 'react'
import { Button, Input, Modal } from '@/components/ui'
import type { WizardData, CatalogueItemData } from '../types'

interface CatalogueStepProps {
  data: WizardData
  onChange: (updates: Partial<WizardData>) => void
}

const EMPTY_ITEM: CatalogueItemData = {
  name: '',
  description: '',
  price: 0,
  unit_of_measure: 'each',
  item_type: 'service',
}

export function CatalogueStep({ data, onChange }: CatalogueStepProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [formItem, setFormItem] = useState<CatalogueItemData>({ ...EMPTY_ITEM })
  const [formError, setFormError] = useState('')

  const items = data.catalogueItems

  const openAdd = () => {
    setEditIndex(null)
    setFormItem({ ...EMPTY_ITEM })
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (index: number) => {
    setEditIndex(index)
    setFormItem({ ...items[index] })
    setFormError('')
    setModalOpen(true)
  }

  const handleSave = () => {
    if (!formItem.name.trim()) {
      setFormError('Name is required')
      return
    }
    const updated = [...items]
    if (editIndex !== null) {
      updated[editIndex] = formItem
    } else {
      updated.push(formItem)
    }
    onChange({ catalogueItems: updated })
    setModalOpen(false)
  }

  const handleDelete = (index: number) => {
    onChange({ catalogueItems: items.filter((_, i) => i !== index) })
  }

  const services = items.filter((i) => i.item_type === 'service')
  const products = items.filter((i) => i.item_type === 'product')

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-text">Your Initial Catalogue</h2>
      <p className="text-sm text-muted">
        These services and products are pre-populated from your trade selection. Edit, add, or remove as needed.
      </p>

      <div className="flex justify-end">
        <Button size="sm" onClick={openAdd}>+ Add item</Button>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted py-4 text-center">
          No catalogue items yet. Add your first service or product.
        </p>
      ) : (
        <div className="space-y-4">
          {services.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text mb-1">Services</h3>
              <div className="space-y-1">
                {services.map((item, _) => {
                  const realIndex = items.indexOf(item)
                  return (
                    <CatalogueRow
                      key={realIndex}
                      item={item}
                      currency={data.currency}
                      onEdit={() => openEdit(realIndex)}
                      onDelete={() => handleDelete(realIndex)}
                    />
                  )
                })}
              </div>
            </div>
          )}

          {products.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text mb-1">Products</h3>
              <div className="space-y-1">
                {products.map((item) => {
                  const realIndex = items.indexOf(item)
                  return (
                    <CatalogueRow
                      key={realIndex}
                      item={item}
                      currency={data.currency}
                      onEdit={() => openEdit(realIndex)}
                      onDelete={() => handleDelete(realIndex)}
                    />
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editIndex !== null ? 'Edit item' : 'Add item'}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault()
            handleSave()
          }}
          className="space-y-4"
        >
          <Input
            label="Name *"
            value={formItem.name}
            onChange={(e) => setFormItem({ ...formItem, name: e.target.value })}
            error={formError}
          />
          <Input
            label="Description"
            value={formItem.description || ''}
            onChange={(e) => setFormItem({ ...formItem, description: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Price"
              type="number"
              value={String(formItem.price)}
              onChange={(e) =>
                setFormItem({ ...formItem, price: parseFloat(e.target.value) || 0 })
              }
            />
            <div className="flex flex-col gap-1">
              <label htmlFor="item-type" className="text-sm font-medium text-text">
                Type
              </label>
              <select
                id="item-type"
                value={formItem.item_type}
                onChange={(e) =>
                  setFormItem({
                    ...formItem,
                    item_type: e.target.value as 'service' | 'product',
                  })
                }
                className="rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <option value="service">Service</option>
                <option value="product">Product</option>
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="unit-of-measure" className="text-sm font-medium text-text">
              Unit of measure
            </label>
            <select
              id="unit-of-measure"
              value={formItem.unit_of_measure}
              onChange={(e) =>
                setFormItem({ ...formItem, unit_of_measure: e.target.value })
              }
              className="rounded-ctl border border-border bg-card px-3 py-2 text-text shadow-sm
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <option value="each">Each</option>
              <option value="hour">Hour</option>
              <option value="kg">Kilogram</option>
              <option value="litre">Litre</option>
              <option value="metre">Metre</option>
              <option value="box">Box</option>
              <option value="pack">Pack</option>
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">
              {editIndex !== null ? 'Save changes' : 'Add item'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

function CatalogueRow({
  item,
  currency,
  onEdit,
  onDelete,
}: {
  item: CatalogueItemData
  currency: string
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="flex items-center gap-3 rounded-ctl border border-border px-3 py-2 text-sm">
      <div className="flex-1 min-w-0">
        <span className="font-medium text-text">{item.name}</span>
        {item.description && (
          <span className="text-muted ml-1">— {item.description}</span>
        )}
      </div>
      <span className="text-muted whitespace-nowrap">
        {currency} {item.price.toFixed(2)}/{item.unit_of_measure}
      </span>
      <div className="flex gap-1">
        <Button size="sm" variant="ghost" onClick={onEdit}>
          Edit
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </div>
  )
}
