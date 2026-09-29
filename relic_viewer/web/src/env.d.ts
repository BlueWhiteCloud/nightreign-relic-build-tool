/// <reference types="vite/client" />

// 让 import.meta.env.xxx 有类型提示，新增环境变量时在这里补一行
interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string
  readonly VITE_API_BASE_URL: string
  readonly VITE_PORT?: string
  readonly VITE_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
