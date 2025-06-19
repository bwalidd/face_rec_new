import axios from "axios";
import { userStore } from "../store/user";
import Cookies from "js-cookie";
import { useNavigate } from "react-router-dom";

axios.defaults.baseURL = import.meta.env.VITE_APP_BACKEND;

const useAxios = () => {
  const navigate = useNavigate();
  const useUserStore = userStore();
  const accessToken = Cookies.get("access_token");
  const axiosInstance = axios.create({
    baseURL: import.meta.env.VITE_APP_BACKEND,
    headers: { Authorization: `Bearer ${accessToken}`,
  
  },
    
  });
  axiosInstance.interceptors.request.use(async (req) => {
    if (!useUserStore.isAccessTokenExpired(accessToken)) return req;
    try {
      const response = await useUserStore.getRefreshToken();

      useUserStore.setAuthUser(response.data.access, response.data.refresh);
      req.headers.Authorization = `Bearer ${response.data.access}`;
      return req;
    } catch (error) {
      navigate("/");
    }
  });

  return axiosInstance;
};

export default useAxios;
