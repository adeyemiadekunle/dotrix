# Astryx migration and component inventory

For the shared CSS layer order, Tailwind token roles, responsive composition rules, and verification commands, see [Astryx and Tailwind integration](astryx-integration.md).

Version: **0.7.15**. Original baseline: `stage` at `c5c3e8110a50b1ccc3c931e4d8f1ce2b0ce5def0`. Integration base: `c17775cab23765f4b771be558a9b05ce741c505b`.

The installed npm package is the API authority. The public website returned HTTP 403 in this environment; website-theme values were checked against the public Meta Astryx source (`56680f6`). This does not claim a pixel-by-pixel website comparison.

## Integration contract

- `packages/ui/src/theme/source.tsx` defines the website-derived paper/ink palette, Figtree typography, Geist Mono code, pill buttons, radii and 900px mobile breakpoint. Generated CSS/JS live alongside the theme source. Regenerate with `pnpm --filter @dotrix/ui theme:build`; verify with `theme:check`.
- `@dotrix/ui/theme`, `@dotrix/ui/astryx` and shared control adapters are the application boundary. Import named public subpaths, not the full library barrel. No application StyleX compiler or network font dependency is required.
- Light, dark, system, saved accent, density and motion preferences remain supported. New accounts default to Astryx; stored accents keep their explicit values. Product reduced motion also disables domain transitions.
- Dotrix's logo, Nova/Kai identities, Phosphor artwork, private conversation model, BYOK, approval flows and backend contracts remain authoritative. Desktop consumes the same web renderer. Email uses the same paper/ink palette with email-safe fallback fonts.
- Existing boards, graphs, annotated diffs, terminals, editable cells, task/date serializers, upload pipelines and evidence/citation renderers stay domain components on shared semantic tokens. Browser-owned selects, file, date and number inputs retain native validation and submission contracts. A retained domain renderer is not an Astryx replacement.
- Removed unused legacy Radix component wrappers, Sonner and the secondary theme provider. Radix Slot remains for existing `asChild` composition. Shiki remains for annotated diffs.

## Newly adopted useful components

Beyond the previous Dotrix controls: AppShell/mobile navigation, ChatLayout/MessageList/Composer/Input, CommandPalette with scopes, searchable Selector, ComplexSelector/RadioList for setup choices, Stepper, Calendar, TreeList, Lightbox, MetadataList, Outline, ResizeHandle/useResizable, HoverCard and toast layers. These reuse existing product data and actions. Dictation, rich token serialization, carousels and new permission-sensitive menus are deferred; they require a product capability, not just a component import.

## Complete published-entry ledger

Every component, documented child and hook shipped in this version appears below, beginning with AppShell and Chat. **Adopted** means explicitly wired by Dotrix. **Library-managed** means a reviewed subcomponent or utility is left to Astryx rather than wired directly; this is not a claim of a direct Dotrix import or a new product feature. **Retained/deferred** explains why a direct replacement would be redundant or change a product contract. This inventory includes components Dotrix did not previously use.

### AppShell

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| AppShell | Adopted | Workspace, account, admin and public site shells. Native mobile navigation and main landmark. | `AppShell/AppShell.doc.mjs` |
| useAppShellMobile | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `AppShell/useAppShellMobile.doc.mjs` |

### Chat

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Chat | Retained/deferred | Compose the lower-level chat primitives with Dotrix run/approval views; generic Chat does not own the domain model. | `Chat/Chat.doc.mjs` |
| ChatComposer | Adopted | Shared Nova composer slots; existing permission and pending-state checks. | `Chat/ChatComposer.doc.mjs` |
| ChatComposerDrawer | Retained/deferred | Existing approval/queue details remain explicit domain sections; no extra composer drawer needed. | `Chat/ChatComposerDrawer.doc.mjs` |
| ChatComposerInput | Adopted | Plain-text messages, native @ project/mode suggestions; no new token serialization. | `Chat/ChatComposerInput.doc.mjs` |
| ChatComposerTokenElement | Retained/deferred | Deferred: messages must remain compatible plain text; no new token payload contract. | `Chat/ChatComposerTokenElement.doc.mjs` |
| ChatDictationButton | Retained/deferred | Deferred: no transcription service or microphone consent flow exists in Dotrix. | `Chat/ChatDictationButton.doc.mjs` |
| ChatLayout | Adopted | Conversation viewport and composer layout. | `Chat/ChatLayout.doc.mjs` |
| ChatLayoutScrollButton | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Chat/ChatLayoutScrollButton.doc.mjs` |
| ChatMessage | Adopted | User and assistant messages with Dotrix agent faces and provenance. | `Chat/ChatMessage.doc.mjs` |
| ChatMessageBubble | Adopted | User message surface. | `Chat/ChatMessageBubble.doc.mjs` |
| ChatMessageList | Adopted | Scroll ownership and following the conversation. | `Chat/ChatMessageList.doc.mjs` |
| ChatMessageMetadata | Retained/deferred | Keep Dotrix sender, time, provenance and usage composition inside ChatMessage. | `Chat/ChatMessageMetadata.doc.mjs` |
| ChatSendButton | Adopted | Send and Stop use existing submission/cancellation callbacks. | `Chat/ChatSendButton.doc.mjs` |
| ChatSystemMessage | Retained/deferred | Existing run failure, steering and private/public notices retain domain rendering on shared tokens. | `Chat/ChatSystemMessage.doc.mjs` |
| ChatTokenizedText | Retained/deferred | Deferred with token serialization; preserve historical plain messages. | `Chat/ChatTokenizedText.doc.mjs` |
| ChatToolCalls | Retained/deferred | Keep permission-aware agent trace structure and artifacts; Collapsible handles disclosure. | `Chat/ChatToolCalls.doc.mjs` |

### AlertDialog

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| AlertDialog | Retained/deferred | Existing confirm flows use Dialog; keep their async approval logic and text. | `AlertDialog/AlertDialog.doc.mjs` |
| useImperativeAlertDialog | Retained/deferred | No duplicate imperative confirmation manager; existing modal store remains authoritative. | `AlertDialog/useImperativeAlertDialog.doc.mjs` |

### animator

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| createAnimator | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `animator/createAnimator.doc.mjs` |

### AspectRatio

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| AspectRatio | Retained/deferred | Existing screenshot/media containment retained; Lightbox supplies inspection. | `AspectRatio/AspectRatio.doc.mjs` |

### Avatar

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Avatar | Adopted | People avatars; Nova/Kai faces remain product assets. | `Avatar/Avatar.doc.mjs` |
| AvatarStatusDot | Retained/deferred | People avatars use Avatar; agent activity retains its domain status semantics. | `Avatar/AvatarStatusDot.doc.mjs` |

### AvatarGroup

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| AvatarGroup | Retained/deferred | Existing collaborator/agent groups preserve individual faces and status. | `AvatarGroup/AvatarGroup.doc.mjs` |
| AvatarGroupOverflow | Retained/deferred | No extra hidden membership surface; preserve existing member visibility rules. | `AvatarGroup/AvatarGroupOverflow.doc.mjs` |

### Badge

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Badge | Adopted | Shared badges and admin pills. | `Badge/Badge.doc.mjs` |

### Banner

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Banner | Adopted | Form errors, offline and admin failures. | `Banner/Banner.doc.mjs` |

### Blockquote

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Blockquote | Retained/deferred | Sanitized Markdown owns blockquotes, styled by shared semantic tokens. | `Blockquote/Blockquote.doc.mjs` |

### BottomSheet

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| BottomSheet | Retained/deferred | AppShell owns mobile navigation and existing dialogs/drawers handle mobile actions. | `BottomSheet/BottomSheet.doc.mjs` |
| BottomSheetSwitcher | Retained/deferred | No independent bottom-sheet route stack. | `BottomSheet/BottomSheetSwitcher.doc.mjs` |

### Breadcrumbs

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| BreadcrumbItem | Adopted | Workspace route links. | `Breadcrumbs/BreadcrumbItem.doc.mjs` |
| Breadcrumbs | Adopted | Workspace breadcrumbs. | `Breadcrumbs/Breadcrumbs.doc.mjs` |

### Button

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Button | Adopted | Shared ActionButton and Button compatibility boundary, site navigation. | `Button/Button.doc.mjs` |

### ButtonGroup

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ButtonGroup | Retained/deferred | Existing action rows remain layout-only; use Button for each action. | `ButtonGroup/ButtonGroup.doc.mjs` |

### Calendar

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Calendar | Adopted | Task date picker; ISO dates retain existing storage format. | `Calendar/Calendar.doc.mjs` |
| useCalendarConstraints | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Calendar/useCalendarConstraints.doc.mjs` |
| useCalendarDays | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Calendar/useCalendarDays.doc.mjs` |
| useCalendarNavigation | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Calendar/useCalendarNavigation.doc.mjs` |

### Card

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Card | Adopted | Setup choices and admin cards. | `Card/Card.doc.mjs` |

### Carousel

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Carousel | Retained/deferred | No rotating content or carousel journey required. | `Carousel/Carousel.doc.mjs` |

### Center

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Center | Retained/deferred | Existing CSS layout remains; no runtime wrapper needed. | `Center/Center.doc.mjs` |

### CheckboxInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| CheckboxInput | Adopted | Selection and acknowledgement controls through SelectionInput. | `CheckboxInput/CheckboxInput.doc.mjs` |

### CheckboxList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| CheckboxList | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `CheckboxList/CheckboxList.doc.mjs` |
| CheckboxListItem | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `CheckboxList/CheckboxListItem.doc.mjs` |

### Citation

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Citation | Retained/deferred | Keep source-label mapping and permission-aware evidence links in Markdown; do not infer sources. | `Citation/Citation.doc.mjs` |

### ClickableCard

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ClickableCard | Retained/deferred | Existing cards contain independent actions/links; avoid nested interactive controls. | `ClickableCard/ClickableCard.doc.mjs` |

### Code

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Code | Adopted | Inline Markdown, file-path actions, branch/command/coverage snippets and admin links use Astryx Code; fenced blocks use CodeBlock. | `Code/Code.doc.mjs` |

### CodeBlock

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| CodeBlock | Adopted | Markdown fenced code with copy and language label. | `CodeBlock/CodeBlock.doc.mjs` |

### Collapsible

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Collapsible | Adopted | Agent trace disclosure. | `Collapsible/Collapsible.doc.mjs` |
| CollapsibleGroup | Retained/deferred | Single trace disclosures use Collapsible; no new synchronized disclosure group required. | `Collapsible/CollapsibleGroup.doc.mjs` |
| useCollapsible | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Collapsible/useCollapsible.doc.mjs` |

### CommandPalette

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| CommandPalette | Adopted | Command/search/workspace selection; existing actions and search scopes. | `CommandPalette/CommandPalette.doc.mjs` |
| CommandPaletteEmpty | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `CommandPalette/CommandPaletteEmpty.doc.mjs` |
| CommandPaletteFooter | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `CommandPalette/CommandPaletteFooter.doc.mjs` |
| CommandPaletteGroup | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `CommandPalette/CommandPaletteGroup.doc.mjs` |
| CommandPaletteInput | Adopted | Search input and scope tabs. | `CommandPalette/CommandPaletteInput.doc.mjs` |
| CommandPaletteItem | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `CommandPalette/CommandPaletteItem.doc.mjs` |
| CommandPaletteList | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `CommandPalette/CommandPaletteList.doc.mjs` |

### ComplexSelector

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ComplexSelector | Adopted | Context/mode choices and setup choice expansion. | `ComplexSelector/ComplexSelector.doc.mjs` |

### ContextMenu

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ContextMenu | Retained/deferred | Existing task/project menu content stays domain-owned via Layer; do not add hidden right-click actions. | `ContextMenu/ContextMenu.doc.mjs` |
| ContextMenuItem | Retained/deferred | Existing menu actions remain in their permission-aware domain list. | `ContextMenu/ContextMenuItem.doc.mjs` |

### DateInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| DateInput | Retained/deferred | Keep native date value/validation where browser-owned; Calendar adopted in task picker. No storage or timezone conversion. | `DateInput/DateInput.doc.mjs` |

### DateRangeInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| DateRangeInput | Retained/deferred | No date-range form contract; existing filters retain separate date endpoints. | `DateRangeInput/DateRangeInput.doc.mjs` |

### DateTimeInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| DateTimeInput | Retained/deferred | No new combined date/time contract; retain existing scheduling serialization. | `DateTimeInput/DateTimeInput.doc.mjs` |

### Dialog

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Dialog | Adopted | Existing modal forms and confirmation flows. | `Dialog/Dialog.doc.mjs` |
| DialogHeader | Retained/deferred | Existing domain header includes linked actions, counts and controls; retain it inside the adopted dialog/drawer. | `Dialog/DialogHeader.doc.mjs` |
| useImperativeDialog | Retained/deferred | Existing modal store drives controlled Dialog. | `Dialog/useImperativeDialog.doc.mjs` |

### Divider

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Divider | Retained/deferred | Existing semantic borders and separators use shared border tokens. | `Divider/Divider.doc.mjs` |

### dragToSnapPoints

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| createDragToSnapPoints | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `dragToSnapPoints/createDragToSnapPoints.doc.mjs` |

### Drawer

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Drawer | Adopted | Task details, preserving nonmodal versus full-screen behavior. | `Drawer/Drawer.doc.mjs` |
| DrawerHeader | Retained/deferred | Existing domain header includes linked actions, counts and controls; retain it inside the adopted dialog/drawer. | `Drawer/DrawerHeader.doc.mjs` |

### DropdownMenu

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| DropdownMenu | Retained/deferred | Domain menus retain existing filter/action semantics through Layer; rich model/context lists use Selector. | `DropdownMenu/DropdownMenu.doc.mjs` |
| DropdownMenuCheckboxItem | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuCheckboxItem.doc.mjs` |
| DropdownMenuDivider | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuDivider.doc.mjs` |
| DropdownMenuGroup | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuGroup.doc.mjs` |
| DropdownMenuItem | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuItem.doc.mjs` |
| DropdownMenuRadioGroup | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuRadioGroup.doc.mjs` |
| DropdownMenuRadioItem | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuRadioItem.doc.mjs` |
| DropdownMenuSubMenu | Retained/deferred | Existing permission-aware domain menus use Layer; model/context choices use Selector. | `DropdownMenu/DropdownMenuSubMenu.doc.mjs` |

### EmptyState

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| EmptyState | Adopted | Shared empty state helper. | `EmptyState/EmptyState.doc.mjs` |

### Field

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Field | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Field/Field.doc.mjs` |
| FieldLabel | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Field/FieldLabel.doc.mjs` |

### FieldStatus

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| FieldStatus | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `FieldStatus/FieldStatus.doc.mjs` |

### FileInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| FileInput | Retained/deferred | Keep native file inputs, existing drop/upload handling, constraints and API; token styling applies to visible actions. | `FileInput/FileInput.doc.mjs` |

### FormLayout

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| FormLayout | Retained/deferred | Existing responsive auth/onboarding/form composition retained around shared inputs. | `FormLayout/FormLayout.doc.mjs` |

### gestures

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| createPanGesture | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `gestures/createPanGesture.doc.mjs` |

### Grid

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Grid | Retained/deferred | Existing responsive board/dashboard grids retained. | `Grid/Grid.doc.mjs` |
| GridSpan | Retained/deferred | Existing responsive grid spans retained. | `Grid/GridSpan.doc.mjs` |

### hooks

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| useAnimatedLayout | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useAnimatedLayout.doc.mjs` |
| useAnimator | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useAnimator.doc.mjs` |
| useAnnounce | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useAnnounce.doc.mjs` |
| useClickableContainer | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useClickableContainer.doc.mjs` |
| useClipboard | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useClipboard.doc.mjs` |
| useContainerReveal | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useContainerReveal.doc.mjs` |
| useDevWarning | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useDevWarning.doc.mjs` |
| useDragToSnapPoints | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useDragToSnapPoints.doc.mjs` |
| useEntryAnimation | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useEntryAnimation.doc.mjs` |
| useFocusTrap | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useFocusTrap.doc.mjs` |
| useGridFocus | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useGridFocus.doc.mjs` |
| useHotkeys | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useHotkeys.doc.mjs` |
| useImageMode | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `hooks/useImageMode.doc.mjs` |
| useIndicatorFocusRing | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useIndicatorFocusRing.doc.mjs` |
| useInputContainer | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useInputContainer.doc.mjs` |
| useInputStatusIcon | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useInputStatusIcon.doc.mjs` |
| useInteractiveRole | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useInteractiveRole.doc.mjs` |
| useKeyboardHint | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useKeyboardHint.doc.mjs` |
| useListFocus | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useListFocus.doc.mjs` |
| useLongPress | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useLongPress.doc.mjs` |
| useMediaQuery | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useMediaQuery.doc.mjs` |
| useMenuPress | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useMenuPress.doc.mjs` |
| useMergedRefs | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useMergedRefs.doc.mjs` |
| useOverflow | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useOverflow.doc.mjs` |
| usePanGesture | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/usePanGesture.doc.mjs` |
| usePressFeedback | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/usePressFeedback.doc.mjs` |
| useScrollLock | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useScrollLock.doc.mjs` |
| useScrollOverflow | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useScrollOverflow.doc.mjs` |
| useScrollableArea | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useScrollableArea.doc.mjs` |
| useStreamingText | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useStreamingText.doc.mjs` |
| useTreeFocus | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useTreeFocus.doc.mjs` |
| useTypeahead | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `hooks/useTypeahead.doc.mjs` |

### HoverCard

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| HoverCard | Adopted | Agent trace details. | `HoverCard/HoverCard.doc.mjs` |
| useHoverCard | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `HoverCard/useHoverCard.doc.mjs` |

### i18n

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| InternationalizationProvider | Adopted | Shared English strings for the current English product. | `i18n/InternationalizationProvider.doc.mjs` |
| useCollator | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `i18n/useCollator.doc.mjs` |
| useDirection | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `i18n/useDirection.doc.mjs` |
| useLocale | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `i18n/useLocale.doc.mjs` |
| useTranslator | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `i18n/useTranslator.doc.mjs` |

### Icon

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Icon | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Icon/Icon.doc.mjs` |
| useIcon | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Icon/useIcon.doc.mjs` |

### IconButton

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| IconButton | Adopted | Sidebar/project actions. | `IconButton/IconButton.doc.mjs` |

### Indicator

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Indicator | Retained/deferred | Keep domain notification/unread indicators and accessible labels. | `Indicator/Indicator.doc.mjs` |

### InfoTip

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| InfoTip | Retained/deferred | Button tooltips/trace HoverCard cover current help; no new hidden instructions. | `InfoTip/InfoTip.doc.mjs` |

### InputGroup

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| InputGroup | Retained/deferred | Shared TextInput plus existing form layout suffices; avoid wrapping native editable cells. | `InputGroup/InputGroup.doc.mjs` |
| InputGroupText | Retained/deferred | No new unit or prefix input required. | `InputGroup/InputGroupText.doc.mjs` |

### Item

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Item | Retained/deferred | Existing issue/trace/session rows have independent actions and domain state; retain their composition. | `Item/Item.doc.mjs` |

### Kbd

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Kbd | Retained/deferred | Existing shortcut hints preserve OS-specific labels and keyboard registry. | `Kbd/Kbd.doc.mjs` |

### Layer

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Layer | Adopted | Existing domain popovers now use shared layer registration and dismissal. | `Layer/Layer.doc.mjs` |
| useLayer | Adopted | Domain popover layer lifecycle; portal inside active dialog when necessary. | `Layer/useLayer.doc.mjs` |

### Layout

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Layout | Retained/deferred | AppShell supplies product layout; existing domain split-pane layouts retain their state. | `Layout/Layout.doc.mjs` |
| LayoutContent | Retained/deferred | Provided by AppShell; not independently wired by Dotrix. | `Layout/LayoutContent.doc.mjs` |
| LayoutFooter | Retained/deferred | Provided by AppShell; not independently wired by Dotrix. | `Layout/LayoutFooter.doc.mjs` |
| LayoutHeader | Retained/deferred | Provided by AppShell; not independently wired by Dotrix. | `Layout/LayoutHeader.doc.mjs` |
| LayoutPanel | Retained/deferred | Provided by AppShell; not independently wired by Dotrix. | `Layout/LayoutPanel.doc.mjs` |

### Lightbox

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Lightbox | Adopted | Coding screenshot inspection and zoom. | `Lightbox/Lightbox.doc.mjs` |
| useLightbox | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Lightbox/useLightbox.doc.mjs` |

### Link

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Link | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Link/Link.doc.mjs` |
| LinkProvider | Adopted | Existing router link adapter in the web app. | `Link/LinkProvider.doc.mjs` |
| useLinkComponent | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Link/useLinkComponent.doc.mjs` |
| useLinkify | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `Link/useLinkify.doc.mjs` |

### List

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| List | Retained/deferred | Existing issue/comment/session lists preserve keyboard, virtualization and permission behavior. | `List/List.doc.mjs` |
| ListItem | Retained/deferred | Existing domain row composition retained. | `List/ListItem.doc.mjs` |

### Markdown

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Markdown | Retained/deferred | Keep react-markdown/remark-gfm with raw HTML disabled and existing citation/file callbacks; CodeBlock and Outline adopted separately. | `Markdown/Markdown.doc.mjs` |

### MetadataList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| MetadataList | Adopted | Coding session token/cost/turn metadata. | `MetadataList/MetadataList.doc.mjs` |
| MetadataListItem | Adopted | Coding session metadata rows. | `MetadataList/MetadataListItem.doc.mjs` |

### MobileNav

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| MobileNav | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `MobileNav/MobileNav.doc.mjs` |

### MoreMenu

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| MoreMenu | Retained/deferred | Existing domain menus preserve item rights and state through Layer. | `MoreMenu/MoreMenu.doc.mjs` |

### MultiSelector

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| MultiSelector | Retained/deferred | Existing multi-value task filters keep domain selection logic; no new saved-value contract. | `MultiSelector/MultiSelector.doc.mjs` |
| useMultiCombobox | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `MultiSelector/useMultiCombobox.doc.mjs` |

### NavIcon

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| NavIcon | Library-managed | Provided through SideNav/TopNav icon slots. | `NavIcon/NavIcon.doc.mjs` |

### NavMenu

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| NavHeadingMenu | Retained/deferred | Workspace switch uses existing command palette; no second workspace selector. | `NavMenu/NavMenu.doc.mjs` |

### NumberInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| NumberInput | Retained/deferred | Keep browser-owned number inputs and current validation to avoid changing values/step semantics. | `NumberInput/NumberInput.doc.mjs` |

### Outline

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Outline | Adopted | Knowledge document heading navigation; appears with multiple headings. | `Outline/Outline.doc.mjs` |
| useOutlineFromMarkdown | Retained/deferred | Headings come from rendered, sanitized react-markdown output so IDs and labels cannot diverge. | `Outline/useOutlineFromMarkdown.doc.mjs` |

### OverflowList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| OverflowList | Retained/deferred | Keep existing responsive truncation and visible important actions; no silently hidden task evidence. | `OverflowList/OverflowList.doc.mjs` |

### Overlay

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Overlay | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Overlay/Overlay.doc.mjs` |
| useOverlay | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Overlay/useOverlay.doc.mjs` |

### Pagination

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Pagination | Retained/deferred | Keep API cursors/infinite lists and existing admin pagination; do not invent totals. | `Pagination/Pagination.doc.mjs` |

### Popover

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Popover | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Popover/Popover.doc.mjs` |
| usePopover | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Popover/usePopover.doc.mjs` |

### PowerSearch

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| PowerSearch | Retained/deferred | Existing permission-scoped search uses CommandPalette with scope tabs; do not replace server search contracts. | `PowerSearch/PowerSearch.doc.mjs` |
| usePowerSearchConfig | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `PowerSearch/usePowerSearchConfig.doc.mjs` |

### ProgressBar

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ProgressBar | Adopted | Shared progress and admin meters. | `ProgressBar/ProgressBar.doc.mjs` |

### RadioList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| RadioList | Adopted | Quick/full setup choices. | `RadioList/RadioList.doc.mjs` |
| RadioListItem | Adopted | Project/context/environment choices. | `RadioList/RadioListItem.doc.mjs` |

### reorderable

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| createReorderable | Retained/deferred | Keep existing board drag/drop and ordering behavior. | `reorderable/createReorderable.doc.mjs` |

### Resizable

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Resizable | Retained/deferred | Keep existing CSS grid and persistent pane widths; useResizable and ResizeHandle own interaction. | `Resizable/Resizable.doc.mjs` |
| useResizable | Adopted | Persistent split pane sizes, bounds and direction. | `Resizable/useResizable.doc.mjs` |

### ScrollableArea

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ScrollableArea | Retained/deferred | ChatMessageList owns chat scrolling; board/terminal/diff need their existing independent scroll containers. | `ScrollableArea/ScrollableArea.doc.mjs` |

### Section

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Section | Retained/deferred | Existing semantic sections and accessible labels retained. | `Section/Section.doc.mjs` |

### SegmentedControl

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| SegmentedControl | Adopted | Preferences and admin controls. | `SegmentedControl/SegmentedControl.doc.mjs` |
| SegmentedControlItem | Adopted | Segmented choices. | `SegmentedControl/SegmentedControlItem.doc.mjs` |

### SelectableCard

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| SelectableCard | Retained/deferred | Setup uses Card and RadioList; no second selection model. | `SelectableCard/SelectableCard.doc.mjs` |

### Selector

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Selector | Adopted | Model, runtime, approval and preference choices; searchable long lists. | `Selector/Selector.doc.mjs` |
| SelectorOption | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Selector/SelectorOption.doc.mjs` |
| useCombobox | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Selector/useCombobox.doc.mjs` |

### SideNav

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| SideNav | Adopted | Workspace and admin navigation. | `SideNav/SideNav.doc.mjs` |
| SideNavCollapseButton | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `SideNav/SideNavCollapseButton.doc.mjs` |
| SideNavHeading | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `SideNav/SideNavHeading.doc.mjs` |
| SideNavItem | Adopted | Workspace route anchors and project links. | `SideNav/SideNavItem.doc.mjs` |
| SideNavSection | Adopted | Workspace/projects and footer organization. | `SideNav/SideNavSection.doc.mjs` |

### Skeleton

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Skeleton | Adopted | Shared loading skeleton. | `Skeleton/Skeleton.doc.mjs` |

### Slider

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Slider | Retained/deferred | No product setting benefits from a new continuous value control; preserve numeric limits. | `Slider/Slider.doc.mjs` |

### SnapPaging

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| useSnapPaging | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `SnapPaging/useSnapPaging.doc.mjs` |

### Spinner

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Spinner | Adopted | Admin loading status. | `Spinner/Spinner.doc.mjs` |

### Stack

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Stack | Retained/deferred | Existing row/column utility layout remains. | `Stack/Stack.doc.mjs` |

### StatusDot

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| StatusDot | Retained/deferred | Retain distinct run/project/presence statuses and their existing labels on shared semantic colors. | `StatusDot/StatusDot.doc.mjs` |

### Stepper

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Step | Adopted | Saved onboarding stages. | `Stepper/Step.doc.mjs` |
| Stepper | Adopted | Named onboarding progress. | `Stepper/Stepper.doc.mjs` |

### Switch

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Switch | Adopted | Settings toggles. | `Switch/Switch.doc.mjs` |

### Table

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Table | Adopted | Shared semantic table boundary and existing admin TanStack data model. | `Table/Table.doc.mjs` |
| TableBody | Adopted | Shared table body. | `Table/TableBody.doc.mjs` |
| TableCell | Adopted | Shared table data. | `Table/TableCell.doc.mjs` |
| TableFooter | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/TableFooter.doc.mjs` |
| TableHeader | Adopted | Shared table header. | `Table/TableHeader.doc.mjs` |
| TableHeaderCell | Adopted | Shared column headers. | `Table/TableHeaderCell.doc.mjs` |
| TableRow | Adopted | Shared table row. | `Table/TableRow.doc.mjs` |
| TableSelectionToolbar | Retained/deferred | Keep existing task bulk actions and permission checks; shared CheckboxInput and tokens apply. | `Table/TableSelectionToolbar.doc.mjs` |
| useTableColumnSettingsState | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/plugins/columnSettings/useTableColumnSettingsState.doc.mjs` |
| useTableSortableState | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/plugins/sortable/useTableSortableState.doc.mjs` |
| useTableColumnResize | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableColumnResize.doc.mjs` |
| useTableColumnSettings | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableColumnSettings.doc.mjs` |
| useTableFilterState | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableFilterState.doc.mjs` |
| useTableFiltering | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableFiltering.doc.mjs` |
| useTableGroupedRows | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableGroupedRows.doc.mjs` |
| useTablePagination | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTablePagination.doc.mjs` |
| useTableRowExpansion | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableRowExpansion.doc.mjs` |
| useTableRowIndex | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableRowIndex.doc.mjs` |
| useTableRowStatus | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableRowStatus.doc.mjs` |
| useTableRowsVirtualization | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableRowsVirtualization.doc.mjs` |
| useTableSelection | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableSelection.doc.mjs` |
| useTableSelectionState | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableSelectionState.doc.mjs` |
| useTableSortable | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableSortable.doc.mjs` |
| useTableStickyColumns | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableStickyColumns.doc.mjs` |
| useTableTreeData | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableTreeData.doc.mjs` |
| useTableTreeState | Retained/deferred | Existing TanStack admin tables and domain task tables retain sorting/filtering/selection/pagination state; only the shared semantic table rendering changes. | `Table/useTableTreeState.doc.mjs` |

### TabList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Tab | Adopted | Command-search scope tabs. | `TabList/Tab.doc.mjs` |
| TabList | Adopted | Home task, Inbox category, project layout, Knowledge, review detail and command-search scope tabs. | `TabList/TabList.doc.mjs` |
| TabMenu | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `TabList/TabMenu.doc.mjs` |

### Text

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Heading | Retained/deferred | Keep semantic native h1–h6 and existing levels; Figtree/token typography applies globally. | `Text/Heading.doc.mjs` |
| Text | Retained/deferred | Keep native text semantics and semantic token styling. | `Text/Text.doc.mjs` |
| useTruncation | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Text/useTruncation.doc.mjs` |

### TextArea

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| TextArea | Adopted | Shared textarea boundary; existing change events, names, validation and refs. | `TextArea/TextArea.doc.mjs` |

### TextInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| TextInput | Adopted | Shared text input boundary including uncontrolled FormData. | `TextInput/TextInput.doc.mjs` |

### theme

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| MediaTheme | Retained/deferred | Current product has no independently themed media surface. | `theme/MediaTheme.doc.mjs` |
| SyntaxTheme | Retained/deferred | CodeBlock supplies syntax colors; annotated diffs retain Shiki token highlighting. | `theme/SyntaxTheme.doc.mjs` |
| Theme | Adopted | Compiled website-derived light/dark theme and reduced-motion variant. | `theme/Theme.doc.mjs` |
| useTheme | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `theme/useTheme.doc.mjs` |
| useThemeName | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `theme/useThemeName.doc.mjs` |

### Thumbnail

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Thumbnail | Retained/deferred | Existing attachment loading, permissions and object URL lifecycle retained. | `Thumbnail/Thumbnail.doc.mjs` |

### TimeInput

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| TimeInput | Retained/deferred | Existing schedule controls retain saved timezone rules; no new time parser. | `TimeInput/TimeInput.doc.mjs` |

### Timer

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Timer | Retained/deferred | Run elapsed time keeps its backend lifecycle and existing formatter. | `Timer/Timer.doc.mjs` |

### Timestamp

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Timestamp | Retained/deferred | Retain date-format, locale/timezone and relative-time helpers already saved in preferences. | `Timestamp/Timestamp.doc.mjs` |

### Toast

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Toast | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Toast/Toast.doc.mjs` |
| useToast | Adopted | Existing notifications, pending queue, Undo and dismissal through ToastHost. | `Toast/useToast.doc.mjs` |

### ToggleButton

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| ToggleButton | Retained/deferred | Existing filters use SegmentedControl or domain selection controls. | `ToggleButton/ToggleButton.doc.mjs` |
| ToggleButtonGroup | Retained/deferred | Existing segmented choices already use SegmentedControl. | `ToggleButton/ToggleButtonGroup.doc.mjs` |

### Token

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Token | Retained/deferred | Existing tag, project and evidence chips carry domain semantics on shared tokens. | `Token/Token.doc.mjs` |

### Tokenizer

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Tokenizer | Retained/deferred | Deferred with rich token message contracts. | `Tokenizer/Tokenizer.doc.mjs` |

### Toolbar

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Toolbar | Retained/deferred | No current standalone product use; existing domain composition stays on shared semantic tokens. | `Toolbar/Toolbar.doc.mjs` |

### Tooltip

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| Tooltip | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Tooltip/Tooltip.doc.mjs` |
| useTooltip | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `Tooltip/useTooltip.doc.mjs` |

### TopNav

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| TopNav | Adopted | Workspace/account/admin/site top navigation. | `TopNav/TopNav.doc.mjs` |
| TopNavHeading | Adopted | Workspace/admin/site heading. | `TopNav/TopNavHeading.doc.mjs` |
| TopNavItem | Adopted | Public navigation. | `TopNav/TopNavItem.doc.mjs` |
| TopNavMegaMenu | Retained/deferred | Current navigation uses TopNav/TopNavItem; no mega-menu or expanded marketing navigation is required. | `TopNav/TopNavMegaMenu.doc.mjs` |
| TopNavMegaMenuFeaturedCard | Retained/deferred | Current navigation uses TopNav/TopNavItem; no mega-menu or expanded marketing navigation is required. | `TopNav/TopNavMegaMenuFeaturedCard.doc.mjs` |
| TopNavMegaMenuItem | Retained/deferred | Current navigation uses TopNav/TopNavItem; no mega-menu or expanded marketing navigation is required. | `TopNav/TopNavMegaMenuItem.doc.mjs` |
| TopNavMenu | Retained/deferred | Current navigation uses TopNav/TopNavItem; no mega-menu or expanded marketing navigation is required. | `TopNav/TopNavMenu.doc.mjs` |

### TreeList

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| TreeList | Adopted | Coding file navigation with stable file paths and changed status. | `TreeList/TreeList.doc.mjs` |

### Typeahead

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| BaseTypeahead | Retained/deferred | Managed by composer/selector internals; no standalone application control. | `Typeahead/BaseTypeahead.doc.mjs` |
| Typeahead | Retained/deferred | Composer uses its built-in trigger suggestions; no separate remote search source needed. | `Typeahead/Typeahead.doc.mjs` |
| TypeaheadItem | Retained/deferred | Managed by composer/selector internals. | `Typeahead/TypeaheadItem.doc.mjs` |

### VisuallyHidden

| Entry | Decision | Placement or rationale | Source in published `src/` |
|---|---|---|---|
| VisuallyHidden | Library-managed | Keep this utility library-owned and use it through higher-level components where needed; no direct Dotrix wiring. | `VisuallyHidden/VisuallyHidden.doc.mjs` |

Inventory total: **264** published entries. Run `node scripts/design/audit-astryx.mjs` after installing dependencies or upgrading Astryx. This verifies coverage, not runtime correctness.

## Verification recorded on 2026-11-13

- Final workspace production builds, type checks and unit tests: **13/13 tasks pass**, including site SSR/prerender and desktop compilation. Web: **169 tests in 20 files** pass. Desktop: **4 tests** pass.
- Chromium journeys: **115 active cases verified across the full run and targeted reruns**; **9 pre-existing legacy cases remain skipped**. The final production-build presentation run passes **30/30 cases**, covering the shared theme, saved preferences, mobile navigation, composer/forms, nested dismissal, inline/fenced code, clipboard, annotated file/diff views and the live Knowledge/Coverage journey. Earlier failing assertions were updated to target visible notifications and semantic headings/navigation rather than Astryx's additional accessibility announcements.
- Full Python suite on the original baseline: **1,588 collected; 1,538 passed, 41 skipped, 9 failed** in 42m51s. All nine failures are opt-in live Anthropic cases enabled by `DOTRIX_LIVE_ANTHROPIC_API_KEY`; deterministic cases pass. **The full Python command exits with failures.** An earlier incomplete/disk-affected attempt is not counted as verification.
- A representative live failure, `test_live_fx_build_change_on_anthropic_waits_for_approval`, also fails in an isolated worktree of the original `stage` baseline at `c5c3e8110a50b1ccc3c931e4d8f1ce2b0ce5def0`, using the same locked fx host dependencies and a separate database (`RuntimeError: libfx operation failed`). None of the failing runtime/test paths were modified by this migration. Live-model quality remains unverified.
- Migrations apply cleanly and match the models. OpenAPI export and client generation produce no contract diff. The fx Node handoff check passes. Locked Python dependency sync and the frozen pnpm lockfile install pass.
- Ruff, ESLint, Prettier, Knip, canonical/reduced/compatibility theme checks and the **264-entry inventory audit** pass. ESLint retains three existing effect-dependency warnings in account/modal code. Vite retains large-chunk warnings; the benchmark below records their scope and the measured route-loading results.
- Public site and admin production pages were rendered at desktop/mobile widths during the migration; refreshed marketing assets show the migrated sample UI. Native Firefox ESR, WebKitGTK and packaged Linux Electron smoke results are recorded below.

The public Astryx website remained inaccessible (HTTP 403); theme values were checked against its public source, and no live pixel comparison is claimed. Production deployment, Windows/macOS installer execution, Safari and physical-device testing were not performed. Live Anthropic checks remain failing. They are opt-in and are skipped when the live-key variable is absent, as in the checked-in CI workflow.

### Latest-stage integration

Before final staging, upstream advanced to `c17775c` through PRs #263 and #264 (coding hardening and engine-version updates). The migration was preserved, the branch fast-forwarded, and all changes reapplied cleanly. A comparison with the saved migration found no unexpected changes. All upstream hardening is retained; duplicate Unreleased Security headings were combined without dropping any entries.

On that refreshed base, all **13 workspace build/type/unit tasks** pass again (**169 web / 4 desktop tests**), and **16 selected live browser journeys** pass, including approvals, project/general chat context, queue/steering/cancellation, publication privacy, linked coding and protected agent guidance. The **128 affected backend/CLI cases** were checked: the batch passed 127 and hit a `PendingRollbackError` in one coding-stream test; that exact test passes when rerun alone (**1 pass, 9.10s**). All new upstream test cases pass. Migrations/model consistency, OpenAPI/client generation, fx handoff, lint, formatting, unused-code checks and generated-theme/inventory checks also pass on this base.

The same **nine opt-in live Anthropic cases still fail** when checked on the refreshed base. The complete 1,588-case run and native packaged-app smoke above were recorded before this upstream refresh; the upstream delta does not change frontend source, dependency manifests, API schemas or migrations. The refreshed CLI runner is covered by the affected source tests. Native packaged-app smoke results use the original-baseline CLI; the temporary old CLI/package artifacts were cleaned up after verification.

## Inline code and file/diff follow-up

Astryx `Code` now renders inline code throughout Markdown, clickable file paths, branch and command snippets, coverage views, worker results and admin links. File-path callbacks remain attached to their existing buttons. Legacy Markdown inline-code overrides and obsolete fenced-Shiki CSS were removed so Astryx owns inline/fenced code styling.

Files and annotated diffs retain their domain renderer and Shiki highlighting: they need separate old/new line numbers, changed-line backgrounds, reference navigation and Juno findings attached to exact new-file lines. The private per-line renderer is named `HighlightedLine` to distinguish it from Astryx's inline `Code`. File rows now expose row headers/cells, and diff rows expose cells to assistive technology.

The 16 code/pane browser checks pass, including existing review/reference/streaming/mobile interactions and new checks for literal/escaped content, inline typography, exact clipboard copies, language labels, unknown/unlabelled fences, long lines, syntax colors across themes, file-path copying, old/new diff line numbers, annotations, and binary/oversized/deleted states. Strengthened fenced dark-mode and exact file-whitespace assertions were rechecked successfully. Web/admin builds and types, all 169 web unit tests, lint, formatting, Knip and the component inventory check pass. Run `pnpm --filter @dotrix/web e2e:design` to include these code/pane checks alongside the earlier presentation suite; it requires no backend or model key.


## Bundle and browser benchmark

The workspace shell and heavy Chat, Codes, Settings, Inbox and Project screens now load on demand. The static entry graph dropped from 2,455,396 to 1,296,138 bytes (745,082 to 409,572 bytes gzipped, a 45% reduction). The web app still warns about optional Shiki language grammars and its WASM asset. Admin (866KB raw) and site (814KB raw) also retain large entry chunks containing their shared providers. Warning thresholds were not raised.

Run `pnpm design:benchmark BEFORE_DIST AFTER_DIST OUTPUT_JSON` against two production builds. [Recorded samples](astryx-performance.json) use Chromium, three cold visits per route, a 1440×900 viewport, 100ms latency, 1.6Mbps download and 4× CPU throttling. The same host was also running verification workloads, so timings are indicative rather than a release performance budget. Network responses are deterministic fixtures, not live-user sessions.

| Route | Before ready median | After ready median | Before LCP median | After LCP median | Before transferred JS | After transferred JS |
|---|---:|---:|---:|---:|---:|---:|
| Login | 10.81s | 10.02s | 9.90s | 9.62s | 752,698 B | 426,168 B |
| Home | 19.20s | 19.74s | 17.48s | 18.70s | 747,982 B | 606,973 B |
| Chat | 13.33s | 12.10s | 12.39s | 11.76s | 747,982 B | 722,367 B |

Route visits also fetch their screen chunks, so their transferred JavaScript differs from the static entry graph. Login and Chat improved in these samples; Home did not. A blanket loading-time improvement is not claimed. Deferred component capabilities remain tied to actual product requirements in the inventory; this verification does not introduce new microphone, rich-token or backend capabilities.


## Platform follow-up

An unpublished Linux x64 Electron directory was built with Electron 44.4.5 and the actual standalone CLI bundle. The bundled CLI starts with `--help`. Under a temporary Xvfb display, the packaged app reports `packaged: true`, renders the production web build, answers its preload/IPC app-info and changelog calls, exposes one main landmark, renders the Astryx light palette, opens/dismisses the command dialog and opens the chat composer without renderer page errors. This is a Linux smoke test, not Windows installer verification or a real-device test.

Full browser verification found legacy toggle CSS covering the member-permission checkbox target. The selection adapter now maps those toggle controls to Astryx Switch and the obsolete toggle CSS is removed; permission save/reload remains covered by the existing live journey.


### Firefox ESR theme compatibility

Firefox ESR 140 ignores CSS `@scope`; native browser execution exposed that the canonical Astryx theme alone left its default palette active. `packages/ui/scripts/theme-compat.mjs` now derives `dotrix-compat.css` from the canonical base/reduced outputs using PostCSS. It replaces each documented theme scope with equivalent selectors rooted at `html[data-astryx-theme]`. Dotrix uses one document-level theme per application; this fallback does not claim nested-theme isolation. Canonical Astryx outputs remain unchanged. Both `theme:build` and `theme:check` include the generated fallback, so an upstream scope shape change fails explicitly instead of silently producing stale CSS.


With that fallback, official Firefox ESR **140.15.0** passes native WebDriver BiDi smoke checks for the light/dark palette, Figtree, a single main landmark, the chat composer, 390px overflow and the mobile navigation/Codes link. No experimental CSS preference was enabled. The official package was extracted into temporary storage; it is not a new application dependency.


Official WebKitGTK **2.52.6** also passes the light/dark palette, loaded Figtree font, single main landmark, chat composer, overflow and native navigation-button/Codes-link smoke checks. Its GTK test window clamps to a **447px** minimum width; the recorded WebKit mobile check uses that actual width. Chromium and Firefox cover 390px. These are Linux engine checks, not Safari or physical-device certification. The temporary WebKit driver uses user-space process-path mapping; no system package or application dependency was added for this check.
