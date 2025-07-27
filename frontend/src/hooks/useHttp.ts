// src/hooks/useHttp.ts

import { Auth } from 'aws-amplify';
import axios, { AxiosError, AxiosResponse } from 'axios';
import useSWR, { SWRConfiguration } from 'swr';

const api = axios.create({
  baseURL: import.meta.env.VITE_APP_API_ENDPOINT,
});

// HTTP Request Preprocessing
api.interceptors.request.use(async (config) => {
  try {
    const user = await Auth.currentAuthenticatedUser();
    if (user) {
      const token = (await Auth.currentSession()).getIdToken().getJwtToken();
      config.headers['Authorization'] = 'Bearer ' + token;
    }
  } catch (e) {
    // Usuario no autenticado
  }

  // Solo establecer Content-Type si no es FormData
  if (!(config.data instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
  }

  return config;
});

const fetcher = (url: string) => {
  return api.get(url).then((res) => res.data);
};

const fetcfWithParams = ([url, params]: [string, Record<string, any>]) => {
  return api.get(url, { params }).then((res) => res.data);
};

const useHttp = () => {
  return {
    get: <Data = any, Error = any>(
      url: string | [string, ...unknown[]] | null,
      config?: SWRConfiguration
    ) => {
      return useSWR<Data, AxiosError<Error>>(
        url,
        typeof url === 'string' ? fetcher : fetcfWithParams,
        {
          ...config,
        }
      );
    },

    getOnce: <RES = any, DATA = any>(
      url: string,
      params?: DATA,
      errorProcess?: (err: any) => void
    ) => {
      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .get<RES, AxiosResponse<RES>, DATA>(url, { params })
          .then(resolve)
          .catch((err) => {
            if (errorProcess) errorProcess(err);
            reject(err);
          });
      });
    },

    post: <RES = any, DATA = any>(
      url: string,
      data: DATA,
      optionsOrErrorProcess?: { headers?: any } | ((err: any) => void),
      maybeErrorProcess?: (err: any) => void
    ) => {
      const isFormData = data instanceof FormData;
      const headers =
        !isFormData && typeof optionsOrErrorProcess === 'object'
          ? optionsOrErrorProcess.headers
          : undefined;
      const errorProcess =
        typeof optionsOrErrorProcess === 'function'
          ? optionsOrErrorProcess
          : maybeErrorProcess;

      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .post<RES, AxiosResponse<RES>, DATA>(url, data, { headers })
          .then(resolve)
          .catch((err) => {
            if (errorProcess) errorProcess(err);
            reject(err);
          });
      });
    },

    put: <RES = any, DATA = any>(
      url: string,
      data: DATA,
      errorProcess?: (err: any) => void
    ) => {
      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .put<RES, AxiosResponse<RES>, DATA>(url, data)
          .then(resolve)
          .catch((err) => {
            if (errorProcess) errorProcess(err);
            reject(err);
          });
      });
    },

    delete: <RES = any, DATA = any>(
      url: string,
      params?: DATA,
      errorProcess?: (err: any) => void
    ) => {
      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .delete<RES, AxiosResponse<RES>, DATA>(url, { params })
          .then(resolve)
          .catch((err) => {
            if (errorProcess) errorProcess(err);
            reject(err);
          });
      });
    },

    patch: <RES = any, DATA = any>(
      url: string,
      data: DATA,
      errorProcess?: (err: any) => void
    ) => {
      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .patch<RES, AxiosResponse<RES>, DATA>(url, data)
          .then(resolve)
          .catch((err) => {
            if (errorProcess) errorProcess(err);
            reject(err);
          });
      });
    },
  };
};

export default useHttp;
