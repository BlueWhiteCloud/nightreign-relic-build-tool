import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'

/**
 * axios 实例：所有后端请求都从这里走。
 * baseURL 取环境变量（开发态是 /api，由 vite 转发到 Python 后端）。
 */
const instance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

instance.interceptors.response.use(
  // 直接把 data 抛出去，业务里 await http.get<T>() 拿到的就是 T
  (response) => response.data,
  (error) => {
    const data = error.response?.data as { message?: string } | undefined
    return Promise.reject(new Error(data?.message || error.message || '请求失败'))
  },
)

/** 用法：const plans = await http.post<Plan[]>('/recommend', { heroType: 3 }) */
export const http = {
  get: <T>(url: string, config?: AxiosRequestConfig) => instance.get<T, T>(url, config),
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    instance.post<T, T>(url, data, config),
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    instance.put<T, T>(url, data, config),
  delete: <T>(url: string, config?: AxiosRequestConfig) => instance.delete<T, T>(url, config),
}

export default instance
