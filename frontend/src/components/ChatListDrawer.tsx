import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { BaseProps } from '../@types/common';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import useDrawer from '../hooks/useDrawer';
import ButtonIcon from './ButtonIcon';
import {
  PiChat,
  PiCheck,
  PiNotePencil,
  PiPencilLine,
  PiRobot,
  PiTrash,
  PiX,
} from 'react-icons/pi';
import { PiCircleNotch } from 'react-icons/pi';
import useConversation from '../hooks/useConversation';
import LazyOutputText from './LazyOutputText';
import DialogConfirmDelete from './DialogConfirmDeleteChat';
import { ConversationMeta } from '../@types/conversation';
import { isMobile } from 'react-device-detect';
import useChat from '../hooks/useChat';
import { useTranslation } from 'react-i18next';
import Menu from './Menu';
import useBot from '../hooks/useBot';
import DrawerItem from './DrawerItem';
import ExpandableDrawerGroup from './ExpandableDrawerGroup';

type Props = BaseProps & {
  onSignOut: () => void;
};

type ItemProps = BaseProps & {
  label: string;
  to: string;
  generatedTitle?: boolean;
  onClick: () => void;
  onDelete: (conversationId: string) => void;
};

const Item: React.FC<ItemProps> = (props) => {
  const { pathname } = useLocation();
  const { conversationId: pathParam } = useParams();
  const { conversationId } = useChat();
  const [tempLabel, setTempLabel] = useState('');
  const [editing, setEditing] = useState(false);
  const { updateTitle } = useConversation();

  const inputRef = useRef<HTMLInputElement>(null);

  const active = useMemo<boolean>(() => {
    return (
      pathParam === props.to ||
      ((pathname === '/' || pathname.startsWith('/bot/')) &&
        conversationId == props.to)
    );
  }, [conversationId, pathParam, pathname, props.to]);

  const onClickEdit = useCallback(() => {
    setEditing(true);
    setTempLabel(props.label);
  }, [props.label]);

  const onClickUpdate = useCallback(() => {
    updateTitle(props.to, tempLabel).then(() => {
      setEditing(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tempLabel, props.to]);

  const onClickDelete = useCallback(() => {
    props.onDelete(props.to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.to]);

  useLayoutEffect(() => {
    if (editing) {
      inputRef.current?.focus();
    }
  }, [editing]);

  useLayoutEffect(() => {
    if (editing) {
      const listener = (e: DocumentEventMap['keypress']) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();

          // dispatch 処理の中で Title の更新を行う（同期を取るため）
          setTempLabel((newLabel) => {
            updateTitle(props.to, newLabel).then(() => {
              setEditing(false);
            });
            return newLabel;
          });
        }
      };
      inputRef.current?.addEventListener('keypress', listener);

      inputRef.current?.focus();

      return () => {
        // eslint-disable-next-line react-hooks/exhaustive-deps
        inputRef.current?.removeEventListener('keypress', listener);
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  return (
    <DrawerItem
      isActive={active}
      isBlur={!editing}
      to={props.to}
      onClick={props.onClick}
      icon={<PiChat />}
      labelComponent={
        <>
          {editing ? (
            <input
              ref={inputRef}
              type="text"
              className="w-full bg-transparent"
              value={tempLabel}
              onChange={(e) => {
                setTempLabel(e.target.value);
              }}
            />
          ) : (
            <>
              {props.generatedTitle ? (
                <LazyOutputText text={props.label} />
              ) : (
                <>{props.label}</>
              )}
            </>
          )}
        </>
      }
      actionComponent={
        <>
          {active && !editing && (
            <>
              <ButtonIcon className="text-base" onClick={onClickEdit}>
                <PiPencilLine />
              </ButtonIcon>

              <ButtonIcon className="text-base" onClick={onClickDelete}>
                <PiTrash />
              </ButtonIcon>
            </>
          )}
          {editing && (
            <>
              <ButtonIcon className="text-base" onClick={onClickUpdate}>
                <PiCheck />
              </ButtonIcon>

              <ButtonIcon
                className="text-base"
                onClick={() => {
                  setEditing(false);
                }}>
                <PiX />
              </ButtonIcon>
            </>
          )}
        </>
      }
    />
  );
};

const ChatListDrawer: React.FC<Props> = (props) => {
  const { t } = useTranslation();
  const { opened, switchOpen } = useDrawer();
  const { conversations } = useConversation();
  const { starredBots } = useBot();

  // const { isAdmin } = useUser();

  const [prevConversations, setPrevConversations] =
    useState<typeof conversations>();
  const [generateTitleIndex, setGenerateTitleIndex] = useState(-1);

  const { deleteConversation } = useConversation();
  const { newChat, conversationId } = useChat();
  const navigate = useNavigate();
  const { botId } = useParams();

  useEffect(() => {
    setPrevConversations(conversations);
  }, [conversations]);

  useEffect(() => {
    // 新規チャットの場合はTitleをLazy表示にする
    if (!conversations || !prevConversations) {
      return;
    }
    if (conversations.length > prevConversations?.length) {
      setGenerateTitleIndex(
        conversations?.findIndex(
          (c) =>
            (prevConversations?.findIndex((pc) => c.id === pc.id) ?? -1) < 0
        ) ?? -1
      );
    }
  }, [conversations, prevConversations]);

  // CORRECCIÓN: Función para cerrar el menú solo si está en móvil y abierto.
  const closeDrawerIfNeeded = useCallback(() => {
    if (isMobile) {
      switchOpen(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [switchOpen]);

  // CORRECCIÓN: Llama a closeDrawerIfNeeded después de la acción.
  const onClickNewChat = useCallback(() => {
    newChat();
    closeDrawerIfNeeded();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newChat, closeDrawerIfNeeded]);

  // CORRECCIÓN: Llama a closeDrawerIfNeeded después de la acción.
  const onClickNewBotChat = useCallback(() => {
    newChat();
    closeDrawerIfNeeded();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newChat, closeDrawerIfNeeded]);

  const [isOpenDeleteModal, setIsOpenDeleteModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    ConversationMeta | undefined
  >();

  const onDelete = useCallback(
    (conversationId: string) => {
      setIsOpenDeleteModal(true);
      setDeleteTarget(conversations?.find((c) => c.id === conversationId));
    },
    [conversations]
  );

  const deleteChat = useCallback(
    (conversationId: string) => {
      deleteConversation(conversationId).then(() => {
        newChat();
        navigate('');
        setIsOpenDeleteModal(false);
        setDeleteTarget(undefined);
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return (
    <>
      <DialogConfirmDelete
        isOpen={isOpenDeleteModal}
        target={deleteTarget}
        onDelete={deleteChat}
        onClose={() => setIsOpenDeleteModal(false)}
      />

      <div
        className={`
          flex h-full flex-col bg-menu-header transition-transform
          duration-300 ease-in-out 
          max-lg:fixed max-lg:inset-y-0
          max-lg:left-0 max-lg:z-40 max-lg:h-screen max-lg:w-64 lg:w-80 lg:flex-shrink-0
          ${opened ? 'max-lg:translate-x-0' : 'max-lg:-translate-x-full'}
        `}>
        <nav className="flex h-full w-full flex-col">
          <div className="flex-grow overflow-y-auto overflow-x-hidden pb-12 scrollbar-thin scrollbar-track-white scrollbar-thumb-menu-header/30">
            <DrawerItem
              isActive={false}
              icon={<PiNotePencil />}
              to=""
              onClick={onClickNewChat}
              labelComponent={t('button.newChat')}
            />
            {/*<DrawerItem
              isActive={false}
              icon={<PiCompass />}
              to="bot/explore"
              labelComponent={t('button.botConsole')}
            />
            {/*{isAdmin && (
              <ExpandableDrawerGroup
                label={t('app.adminConsoles')}
                className="border-t pt-1">
                <DrawerItem
                  isActive={false}
                  icon={<PiShareNetwork />}
                  to="admin/shared-bot-analytics"
                  labelComponent={t('button.sharedBotAnalytics')}
                />
                <DrawerItem
                  isActive={false}
                  icon={<PiGlobe />}
                  to="admin/api-management"
                  labelComponent={t('button.apiManagement')}
                />
                {/* <DrawerItem
                  isActive={false}
                  icon={<PiUsersThree />}
                  to="admin/user-usages"
                  labelComponent={t('button.userUsages')}
                /> 
              </ExpandableDrawerGroup>
            )}*/}

            <ExpandableDrawerGroup
              label={t('app.starredBots')}
              className="border-t pt-1">
              {starredBots?.map((bot) => (
                <DrawerItem
                  key={bot.id}
                  isActive={botId === bot.id && !conversationId}
                  to={`bot/${bot.id}`}
                  icon={<PiRobot />}
                  labelComponent={bot.title}
                  onClick={onClickNewBotChat}
                />
              ))}
            </ExpandableDrawerGroup>

            {/*<ExpandableDrawerGroup
              label={t('app.recentlyUsedBots')}
              className="border-t pt-1">
              {recentlyUsedUnsterredBots
                ?.slice(0, 3)
                .map((bot) => (
                  <DrawerItem
                    key={bot.id}
                    isActive={false}
                    to={`bot/${bot.id}`}
                    icon={<PiRobot />}
                    labelComponent={bot.title}
                    onClick={onClickNewBotChat}
                  />
                ))}
            </ExpandableDrawerGroup>*/}

            <ExpandableDrawerGroup
              label={t('app.conversationHistory')}
              className="border-t pt-1">
              {conversations === undefined && (
                <div className="flex animate-spin items-center justify-center p-4">
                  <PiCircleNotch size={24} />
                </div>
              )}
              {conversations?.map((conversation, idx) => (
                <Item
                  key={idx}
                  className="grow"
                  label={conversation.title}
                  to={conversation.id}
                  generatedTitle={idx === generateTitleIndex}
                  // CORRECCIÓN: Pasa la función para que el menú se cierre en móvil al hacer clic.
                  onClick={() => {
                    navigate(conversation.id);
                    setTimeout(() => {
                      switchOpen(false);
                    }, 100);
                  }}
                  onDelete={onDelete}
                />
              ))}
            </ExpandableDrawerGroup>
          </div>

          <div className="h-12 w-full flex-shrink-0 border-r border-t bg-menu-header">
            <Menu onSignOut={props.onSignOut} />
          </div>
        </nav>
      </div>

      {opened && (
        <div className="lg:hidden">
          <ButtonIcon
            className="fixed left-64 top-2 z-50 text-white"
            onClick={() => switchOpen(false)}>
            <PiX size={24} />
          </ButtonIcon>
          <div
            className="fixed inset-0 z-30 bg-dark-gray/90"
            onClick={() => switchOpen(false)}></div>
        </div>
      )}
    </>
  );
};

export default ChatListDrawer;
