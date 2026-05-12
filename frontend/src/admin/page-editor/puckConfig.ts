/**
 * Puck editor configuration — the single source of truth for all
 * components available to the visual page editor.
 *
 * This config is consumed by BOTH:
 *   1. `<Puck config={puckConfig} ... />` in `PageEditorEdit.tsx` (admin).
 *   2. `<Render config={puckConfig} ... />` in `PublicPageRenderer.tsx`
 *      and `ManagedPage.tsx` (public renderer).
 *
 * The sharing is intentional — Puck's `<Render>` walks the `data` tree
 * and looks up each node's `type` in `config.components[type].render`
 * to produce the output HTML. If the editor and the renderer used
 * different configs, published content could render differently from
 * what was authored.
 *
 * Component render functions and field schemas live in
 * `./components/*.tsx` (see the barrel file `./components/index.ts`).
 *
 * Categories below are optional hints to Puck's component picker UI —
 * they group the 19 components into logical sections (Layout, Content,
 * Media, Marketing, Actions) so the picker is scannable at a glance.
 * If a future component is added, remember to also register it in the
 * appropriate category, otherwise Puck will dump it into an untitled
 * catch-all group.
 *
 * Note: the 19th component `NZTrustSignals` is the "+1" beyond the
 * 18 originally scoped — it's NZ-specific so slotted into the
 * `marketing` category alongside the other conversion-focused blocks.
 */
import type { Config } from '@puckeditor/core'
import {
  HeroComponent,
  FeatureGridComponent,
  SectionComponent,
  ColumnsComponent,
  HeadingComponent,
  RichTextComponent,
  ImageBlockComponent,
  VideoEmbedComponent,
  ButtonComponent,
  FAQAccordionComponent,
  PricingCardComponent,
  TestimonialCardComponent,
  CTABannerComponent,
  SpacerComponent,
  DividerComponent,
  BadgeComponent,
  ListComponent,
  DemoRequestFormComponent,
  NZTrustSignalsComponent,
} from './components'

export const puckConfig: Config = {
  components: {
    // Layout
    Section: SectionComponent,
    Columns: ColumnsComponent,
    Spacer: SpacerComponent,
    Divider: DividerComponent,

    // Content
    Hero: HeroComponent,
    CTABanner: CTABannerComponent,
    Heading: HeadingComponent,
    RichText: RichTextComponent,
    List: ListComponent,
    Badge: BadgeComponent,

    // Media (Image is keyed as "Image" per design doc — the underlying
    // component is named `ImageBlockComponent` to avoid clashing with
    // the native browser `Image` global).
    Image: ImageBlockComponent,
    VideoEmbed: VideoEmbedComponent,

    // Marketing
    FeatureGrid: FeatureGridComponent,
    PricingCard: PricingCardComponent,
    TestimonialCard: TestimonialCardComponent,
    FAQAccordion: FAQAccordionComponent,
    DemoRequestForm: DemoRequestFormComponent,
    NZTrustSignals: NZTrustSignalsComponent,

    // Actions
    Button: ButtonComponent,
  },
  categories: {
    layout: {
      title: 'Layout',
      components: ['Section', 'Columns', 'Spacer', 'Divider'],
    },
    content: {
      title: 'Content',
      components: ['Hero', 'CTABanner', 'Heading', 'RichText', 'List', 'Badge'],
    },
    media: {
      title: 'Media',
      components: ['Image', 'VideoEmbed'],
    },
    marketing: {
      title: 'Marketing',
      components: [
        'FeatureGrid',
        'PricingCard',
        'TestimonialCard',
        'FAQAccordion',
        'DemoRequestForm',
        'NZTrustSignals',
      ],
    },
    actions: {
      title: 'Actions',
      components: ['Button'],
    },
  },
}
