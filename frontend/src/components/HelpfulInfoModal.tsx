import React, { useState, useEffect } from 'react';
import { PiLinkSimple, PiWarningCircle } from 'react-icons/pi';
import Button from './Button'; // Ajusta la ruta según tu proyecto

const HelpfulInfoModal = () => {
  const [isInfoOpen, setIsInfoOpen] = useState(false);
  const [isDisclaimerOpen, setIsDisclaimerOpen] = useState(false);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsInfoOpen(false);
        setIsDisclaimerOpen(false);
      }
    };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, []);

  return (
    <>
      <div className="flex gap-2">
        <Button
          className="bg-aws-paper p-2 text-sm"
          outlined
          onClick={() => setIsInfoOpen(true)}
        >
          <PiLinkSimple className="mr-2" />
          Referencias
        </Button>

        <Button
          className="bg-aws-paper p-2 text-sm"
          outlined
          onClick={() => setIsDisclaimerOpen(true)}
        >
          <PiWarningCircle className="mr-2" />
          Disclaimer
        </Button>
      </div>

      {/* Modal Información */}
      {isInfoOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setIsInfoOpen(false)}
        >
          <div
            className="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto shadow-lg relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsInfoOpen(false)}
              className="absolute top-3 right-4 text-gray-500 hover:text-gray-700 text-xl"
            >
              ✕
            </button>
            <h2 className="text-xl font-semibold mb-4">¿Qué es la Hiperamonemia?</h2>
            <div className="text-sm text-gray-700 space-y-4">
              <p>
                La hiperamonemia es una condición clínica caracterizada por niveles elevados de amoníaco en sangre, resultado de una alteración en el metabolismo del nitrógeno, particularmente en el ciclo de la urea. Esta condición puede ser hereditaria —como los errores innatos del metabolismo— o adquirida, asociada comúnmente a enfermedades hepáticas severas. El amoníaco, al no poder eliminarse eficazmente, se acumula y atraviesa la barrera hematoencefálica, generando efectos neurotóxicos.
              </p>
              <p>
                Las manifestaciones clínicas pueden variar ampliamente según la etiología y la edad de presentación. En neonatos, puede incluir vómitos, letargo, hipotonía, convulsiones y coma. En adultos, puede cursar con alteraciones del estado mental, confusión, comportamiento anormal o incluso coma hepático. El diagnóstico se confirma mediante la cuantificación de amoníaco sérico y pruebas metabólicas complementarias.
              </p>
              <p>
                El tratamiento de la hiperamonemia requiere una intervención urgente. Las estrategias terapéuticas incluyen la restricción proteica, administración de agentes como benzoato o fenilbutirato de sodio, diálisis en casos severos y, cuando sea aplicable, el tratamiento del trastorno subyacente o incluso trasplante hepático. La intervención temprana es fundamental para reducir el riesgo de secuelas neurológicas permanentes.
              </p>
              <p>
                La evaluación genética puede ser crucial en pacientes con sospecha de defectos congénitos del metabolismo, permitiendo el asesoramiento familiar y la planificación de futuras gestaciones. Por lo tanto, la hiperamonemia no solo representa una urgencia médica, sino también un desafío diagnóstico y terapéutico multidisciplinario.
              </p>
              <p>
                Fuente: Summar, M. L., & Tuchman, M. (2001). <i>Hiperammonemia: diagnosis and management strategies</i>. <b>Pediatrics</b>, 107(4), 726-735. Recuperado de: <a href="https://publications.aap.org/pediatrics/article/107/4/726/66062/Hyperammonemia-Diagnosis-and-Management-Strategies" target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">AAP Pediatrics</a>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Modal Disclaimer */}
      {isDisclaimerOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setIsDisclaimerOpen(false)}
        >
          <div
            className="bg-white rounded-lg p-6 max-w-3xl w-full max-h-[80vh] overflow-y-auto shadow-lg relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsDisclaimerOpen(false)}
              className="absolute top-3 right-4 text-gray-500 hover:text-gray-700 text-xl"
            >
              ✕
            </button>
            <h2 className="text-xl font-semibold mb-4">Disclaimer / Descargo de responsabilidad</h2>
            <div className="text-sm text-gray-700 space-y-4">
              <p>
                Este chatbot de Hiperamonemia es una herramienta de apoyo diseñada exclusivamente para médicos. Su propósito principal es proporcionar orientación en el diagnóstico, tratamiento y manejo clínico de pacientes, además de ayudar a identificar posibles candidatos para estudios genéticos relacionados. Sin embargo, no debe considerarse como un sustituto del juicio clínico profesional ni del diagnóstico médico.
              </p>
              <p className="font-semibold">Condiciones de uso:</p>
              <ol className="list-decimal list-inside space-y-2 pl-4">
                <li>Este chatbot no sustituye el juicio clínico ni la responsabilidad profesional del médico usuario. La herramienta está diseñada para complementar, no reemplazar, la evaluación médica integral.</li>
                <li>El médico usuario debe emplear su criterio clínico en todo momento y verificar cualquier información proporcionada antes de aplicarla en la práctica clínica, considerando las circunstancias individuales de cada paciente.</li>
                <li>La información proporcionada debe interpretarse como una orientación y debe ser validada por el médico tratante antes de tomar cualquier decisión diagnóstica o terapéutica.</li>
                <li>Este chatbot <strong>NO</strong> establece una relación médico-paciente.</li>
                <li>El uso de esta herramienta está restringido a profesionales de la salud capacitados y autorizados, quienes son responsables de interpretar y aplicar la información de manera adecuada.</li>
                <li>El usuario entiende y acepta que esta herramienta no garantiza la exactitud, actualidad, exhaustividad o aplicabilidad de la información en todos los contextos clínicos.</li>
                <li>Limitaciones de responsabilidad: Los desarrolladores y distribuidores de este chatbot no asumen responsabilidad por decisiones clínicas basadas exclusivamente en los resultados generados por esta herramienta. Los creadores y los desarrolladores de este chatbot no se hacen responsables por cualquier consecuencia derivada del uso o mal uso de esta herramienta.</li>
                <li>Confidencialidad y privacidad: El uso de esta herramienta debe cumplir con todas las normativas aplicables sobre la protección de datos y confidencialidad del paciente. Se recomienda que los médicos usuarios empleen la herramienta en entornos seguros y respeten la privacidad de la información recopilada a través del chatbot. Los datos ingresados en el chatbot no serán almacenados ni compartidos con terceros sin la debida autorización o consentimiento.</li>
                <li>Actualización de la herramienta: Esta herramienta es susceptible de mejoras y actualizaciones periódicas para optimizar su funcionamiento y la calidad de la información proporcionada. Los usuarios son responsables de asegurarse de estar utilizando la versión más reciente del chatbot para minimizar errores o desactualizaciones.</li>
              </ol>
              <p>
                <u>
                  Al utilizar este chatbot, el médico usuario acepta todo lo previamente expuesto y declara entender plenamente que su uso está sujeto a todas esas condiciones.
                </u>
              </p>
              <p>
                En caso de emergencia médica, se recomienda contactar directamente a expertos en el tema, incluyendo profesionales de Genética Humana, para una evaluación y manejo más detallado.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default HelpfulInfoModal;
