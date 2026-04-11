// Arrow.js type augmentation — the library's built-in types don't
// properly expose reactive proxy properties.
declare module '@arrow-js/core' {
  export function reactive<T extends object>(data: T): T
  export function html(strings: TemplateStringsArray, ...exprs: any[]): ArrowTemplate
  export interface ArrowTemplate {
    (el: Element): void
    isT: true
    key: string
    id: number
    _c: any
    _k: any
  }
}
