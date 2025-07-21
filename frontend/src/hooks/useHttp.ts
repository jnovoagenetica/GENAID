// src/hooks/useHttp.ts

import { Auth } from 'aws-amplify';
import axios, { AxiosError, AxiosResponse } from 'axios';
import useSWR, { SWRConfiguration } from 'swr';

const api = axios.create({
  baseURL: import.meta.env.VITE_APP_API_ENDPOINT,
});


// /---------------------------------------\
// |    INICIO DE LA CORRECCIÓN CLAVE      |
// \---------------------------------------/
// HTTP Request Preprocessing
api.interceptors.request.use(async (config) => {
  // Si está autenticado, se añade el token de ID al encabezado de la petición
  try {
    const user = await Auth.currentAuthenticatedUser();
    if (user) {
      const token = (await Auth.currentSession()).getIdToken().getJwtToken();
      config.headers['Authorization'] = 'Bearer ' + token;
    }
  } catch (e) {
    // No hacer nada si el usuario no está autenticado
  }

  // Lógica inteligente para el Content-Type:
  // Si el cuerpo de la petición NO es FormData, entonces asumimos que es JSON.
  if (!(config.data instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
  }
  // Si SÍ es FormData, no ponemos ninguna cabecera de Content-Type.
  // El navegador lo hará automáticamente, lo cual es necesario para las subidas de archivos.

  return config;
});
// /---------------------------------------\
// |      FIN DE LA CORRECCIÓN CLAVE       |
// \---------------------------------------/


const fetcher = (url: string) => {
  return api.get(url).then((res) => res.data);
};

const fetcfWithParams = ([url, params]: [string, Record<string, any>]) => {
  return api
    .get(url, {
      params,
    })
    .then((res) => res.data);
};

const useHttp = () => {
  return {
    get: <Data = any, Error = any>(
      url: string | [string, ...unknown[]] | null,
      config?: SWRConfiguration
    ) => {
      // eslint-disable-next-line react-hooks/rules-of-hooks
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
          .get<RES, AxiosResponse<RES>, DATA>(url, {
            params,
          })
          .then((data) => {
            resolve(data);
          })
          .catch((err) => {
            if (errorProcess) {
              errorProcess(err);
            }
            reject(err);
          });
      });
    },

    post: <RES = any, DATA = any>(
      url: string,
      data: DATA,
      errorProcess?: (err: any) => void
    ) => {
      return new Promise<AxiosResponse<RES>>((resolve, reject) => {
        api
          .post<RES, AxiosResponse<RES>, DATA>(url, data)
          .then((data) => {
            resolve(data);
          })
          .catch((err) => {
            if (errorProcess) {
              errorProcess(err);
            }
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
          .then((data) => {
            resolve(data);
          })
          .catch((err) => {
            if (errorProcess) {
              errorProcess(err);
            }
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
          .delete<RES, AxiosResponse<RES>, DATA>(url, {
            params,
          })
          .then((data) => {
            resolve(data);
          })
          .catch((err) => {
            if (errorProcess) {
              errorProcess(err);
            }
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
          .then((data) => {
            resolve(data);
          })
          .catch((err) => {
            if (errorProcess) {
              errorProcess(err);
            }
            reject(err);
          });
      });
    },
  };
};

export default useHttp;