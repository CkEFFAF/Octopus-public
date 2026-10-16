/// <reference types="vite/client" />

declare module "*.less" {
  const classes: { [key: string]: string };
  export default classes;
}

interface ImportMetaEnv {
  readonly VITE_OCTOP_ICP_FILING_NUMBER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
