import React, { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { twMerge } from 'tailwind-merge';

type Props = {
  className?: string;
  isActive?: boolean;
  isBlur?: boolean;
  to: string;
  icon: ReactNode;
  labelComponent: ReactNode;
  actionComponent?: ReactNode;
  onClick?: () => void;
};

const DrawerItem: React.FC<Props> = (props) => {
  return (
    <Link
      className={twMerge(
        'group mx-2 my-1 flex h-10 items-center  rounded px-2',
        props.isActive ?? true
          ? 'bg-boton-header'
          : 'hover:bg-boton-header',
        props.className
      )}
      to={props.to}
      onClick={props.onClick}>
      <div className={`flex items-center h-8 max-h-8 justify-start overflow-hidden`}>
        <div className="mr-2 pt-0.5">{props.icon}</div>
        <div className="relative flex-1 text-ellipsis break-all truncate max-w-[300px]">
          {props.labelComponent}
          {(props.isBlur ?? true) && (
            <div
              className={twMerge(
                'absolute inset-y-0 right-0 w-8 bg-gradient-to-l',
                props.isActive
                  ? 'from-boton-header'
                  //Quitamos la linea de from-aws-squid-ink por que estaba dando un degradado que no se necesita
                  : 'group-hover:from-boton-header-hover'
              )}
            />
          )}
        </div>

        <div className="flex">{props.actionComponent}</div>
      </div>
    </Link>
  );
};

export default DrawerItem;
