import React, { ReactNode, cloneElement, ReactElement, useState } from 'react';
import { BaseProps } from '../@types/common';
import { Authenticator } from '@aws-amplify/ui-react';
import { SocialProvider } from '@aws-amplify/ui';
import { useAuthenticator } from '@aws-amplify/ui-react';
import { PiPlayCircle, PiX } from 'react-icons/pi';
// ===== CORRECCIÓN DEL NOMBRE DE ARCHIVO =====
import videoSrc from '../assets/VideAprendizaje.mp4';

type Props = BaseProps & {
  socialProviders: SocialProvider[];
  children: ReactNode;
};

const AuthAmplify: React.FC<Props> = ({ socialProviders, children }) => {
  const { signOut } = useAuthenticator();
  const [isVideoModalOpen, setIsVideoModalOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setIsVideoModalOpen(true)}
        className="fixed bottom-5 right-5 z-20 flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-gray-700 shadow-lg ring-1 ring-gray-200 transition-transform hover:scale-105"
      >
        <PiPlayCircle size={22} />
        <span className="font-semibold">Aprende a usar la App</span>
      </button>

      {isVideoModalOpen && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black bg-opacity-70"
          onClick={() => setIsVideoModalOpen(false)}
        >
          <div
            className="relative w-full max-w-4xl rounded-lg bg-black p-2 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsVideoModalOpen(false)}
              className="absolute -right-3 -top-3 z-50 rounded-full bg-white p-1 text-black transition-transform hover:scale-110"
            >
              <PiX size={24} />
            </button>
            <video
              className="h-auto w-full rounded"
              src={videoSrc}
              controls
              autoPlay
              loop
            />
          </div>
        </div>
      )}

      <Authenticator
        socialProviders={socialProviders}
        hideSignUp
        components={{
          Header: () => (
            <div className="mb-5 mt-20 flex flex-col items-center justify-center gap-4 px-4">
              <div className="flex flex-col sm:flex-row items-center justify-center gap-4 w-full max-w-screen-md">
                <img
                  src="/Gentica_Humana.png"
                  alt="Logo Genética Humana"
                  className="h-32 sm:h-40 md:h-48 w-auto object-contain"
                />
                <img
                  src="/GeneticaLogoAid.png"
                  alt="Logo GHeneAid"
                  className="h-32 sm:h-40 md:h-48 w-auto object-contain"
                />
              </div>
            </div>
          ),
        }}
      >
        <>{cloneElement(children as ReactElement, { signOut })}</>
      </Authenticator>
    </>
  );
};

export default AuthAmplify;