// Édition de l'application : « scalp » (memecoins) ou « tech » (projets technologiques).
export type Edition = "scalp" | "tech";
let current: Edition = "scalp";
export const setEdition = (e: string | undefined) => { current = e === "tech" ? "tech" : "scalp"; };
export const edition = () => current;
export const isTech = () => current === "tech";
export const appName = () => (isTech() ? "Solana Tech Analyst" : "Solana AI Analyst");
export const appFullName = () => (isTech() ? "Solana Tech Analyst" : "Solana AI Desktop Analyst");
