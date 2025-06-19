import {create} from 'zustand'
type STORE = {
    gpus: number
}
type ACTION = {
    setGpu: (data: number) => void,
}

export const useGpuStore = create<STORE & ACTION>((set) => ({
    gpus: 4, // Default to 4 GPUs
    setGpu(data) {
        set(({gpus: data}))
    }    
}))