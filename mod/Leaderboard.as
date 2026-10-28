package
{
   import _kiwi.Controls.BagContainerBasic;
   import _kiwi.Controls.DirectionalMapping;
   import _kiwi.Controls.RadioButton;
   import _kiwi.Controls.RowView;
   import _kiwi.Controls.SlotBasic;
   import _kiwi.Controls.WindowHeaderSmall;
   import _kiwi.Core.UIComponent;
   import _kiwi.Util.NumberFormat;
   import flash.display.MovieClip;
   import flash.display.Sprite;
   import flash.text.TextFieldAutoSize;
   import flash.utils.Timer;
   import flash.events.TimerEvent;
   import flash.events.Event;
   import flash.events.MouseEvent;
   import flash.external.ExternalInterface;
   import flash.filters.BitmapFilterQuality;
   import flash.filters.GlowFilter;
   import flash.geom.Point;
   import flash.text.TextField;
   import flash.text.TextFormat;
   import flash.utils.Dictionary;

   public class Leaderboard extends UIComponent
   {

      private static const TOOLTIP_PADDING:* = 10;

      private static var FILTER_EVERYONE:int = 0;

      private static var FILTER_FRIENDS:int = 1;

      public const ITEMS_PER_PAGE:int = 10;

      private const SLOTS_PER_ROW:int = 3;

      public var winHeader:WindowHeaderSmall;

      public var categoryView:RowView;

      public var leaderboardView:RowView;

      public var leaderboardFooterMC:MovieClip;

      public var leaderboardHeaderMC:MovieClip;

      public var loadingMC:MovieClip;

      public var contestRewardsMC:MovieClip;

      public var sectionCategorySelectHighlight:MovieClip;

      public var sectionFiltersSelectHighlight:MovieClip;

      public var sectionRewardsSelectHighlight:MovieClip;

      public var leaderboardInfos:Array = [];

      public var currentLeaderboard:Number = -1;

      public var currentCategory:int = -1;

      public var frame:MovieClip;

      public var categoryBags:Dictionary = new Dictionary();

      public var addedCategories:int = 0;

      public var numEntries:int = 0;

      public var _entryIndex:int = 0;

      private var currentFilterHighlight:MovieClip;


      // Game Hub: isolated collector controls, preserving the stock UI.
      private var ghCatalog:String = "kind\tcategoryId\tcategoryName\tleaderboardId\tleaderboardName\tparam4\tparam5\tscoreType\tisDefault\tleaderboardDisplayName";
      private var ghCategories:Object = {};
      private var ghIds:Array = [];
      private var ghConfigIds:String = "";
      private var ghProgress:String = "";
      private var ghPanel:Sprite;
      private var ghStatus:TextField;
      private var ghTimer:Timer = new Timer(8000,1);
      private var ghRunning:Boolean = false;
      private var ghAuto:Boolean = false;
      private var ghWaiting:Boolean = false;
      private var ghAdvancing:Boolean = false;
      private var ghBoardIndex:int = 0;
      private var ghBoard:Number = -1;
      private var ghStart:int = 0;
      private var ghEnd:int = 0;
      private var ghSaved:int = 0;
      private var ghTotal:int = 0;
      private var ghCount:int = 0;
      private var ghWanted:int = 0;
      private var ghRun:String = "";
      private var ghRows:String = "";

      public function Leaderboard()
      {
         super();
         if(IggyFunctions.inIggy) ExternalInterface.addCallback("loadModConfiguration",this.ghLoadConfig);
         addFrameScript(0,this.frame1,10,this.frame11);
         this.__setProp_winHeader_Scene1_header_0();
      }

      public function get lastPageIndex() : int
      {
         if(this.numEntries == 0)
         {
            return 0;
         }
         return this.ITEMS_PER_PAGE * (Math.ceil(this.numEntries / this.ITEMS_PER_PAGE) - 1);
      }

      public function get entryIndex() : int
      {
         return this._entryIndex;
      }

      public function set entryIndex(param1:int) : void
      {
         this._entryIndex = param1;
         var _loc2_:int = this.entryIndex / this.ITEMS_PER_PAGE + 1;
         var _loc3_:int = this.lastPageIndex / this.ITEMS_PER_PAGE + 1;
         this.leaderboardFooterMC.btnPageFirst.enabled = _loc2_ > 1;
         this.leaderboardFooterMC.btnPageLeft.enabled = _loc2_ > 1;
         this.leaderboardFooterMC.btnPageRight.enabled = _loc2_ < _loc3_;
      }

      public function get resultsOnPage() : int
      {
         return Math.min(this.ITEMS_PER_PAGE,this.numEntries - this.entryIndex + 1) - 1;
      }

      override protected function configUI() : void
      {
         var _loc2_:int = 0;
         super.configUI();
         if(IggyFunctions.inIggy)
         {
            ExternalInterface.addCallback("addCategory",this.addCategory);
            ExternalInterface.addCallback("addLeaderboard",this.addLeaderboard);
            ExternalInterface.addCallback("removeLeaderboard",this.removeLeaderboard);
            ExternalInterface.addCallback("setLeaderboard",this.setLeaderboard);
            ExternalInterface.addCallback("setLeaderboardInfo",this.setLeaderboardInfo);
            ExternalInterface.addCallback("addLeaderboardEntry",this.addLeaderboardEntry);
            ExternalInterface.addCallback("getEntriesRangeFailed",this.getEntriesRangeFailed);
            ExternalInterface.addCallback("getEntriesNearPlayerFailed",this.getEntriesNearPlayerFailed);
            ExternalInterface.addCallback("setCategory",this.setCategory);
            ExternalInterface.addCallback("setLeaderboardFailed",this.setLeaderboardFailed);
            ExternalInterface.addCallback("updateRewardDisplayOrder",this.updateRewardDisplayOrder);
            ExternalInterface.addCallback("setRewardInfo",this.setRewardInfo);
            ExternalInterface.addCallback("clearRewardInfos",this.clearRewardInfos);
            ExternalInterface.addCallback("setTimeUntilReset",this.setTimeUntilReset);
            ExternalInterface.addCallback("setMaxEarnedReward",this.setMaxEarnedReward);
            ExternalInterface.addCallback("GET_CONFIGURED_DATA",this.getConfigured);
            ExternalInterface.addCallback("HIGHLIGHT_CATEGORY",this.highlightCategory);
            ExternalInterface.addCallback("UNHIGHLIGHT_CATEGORY",this.unhighlightCategory);
            ExternalInterface.addCallback("SWITCH_CATEGORY",this.switchCategory);
            ExternalInterface.addCallback("COLLAPSE_CATEGORY",this.collapseCategory);
            ExternalInterface.addCallback("HIGHLIGHT_SLOT",this.highlightSlot);
            ExternalInterface.addCallback("UNHIGHLIGHT_SLOT",this.unhighlightSlot);
            ExternalInterface.addCallback("ACTIVATE_SLOT",this.activateSlot);
            ExternalInterface.addCallback("SWITCH_SECTIONS",this.switchSections);
            ExternalInterface.addCallback("MOVE_FILTERS_CURSOR",this.moveFiltersCursor);
            ExternalInterface.addCallback("MOVE_REWARDS_CURSOR",this.moveRewardsCursor);
            ExternalInterface.addCallback("PAGE_FIRST_SELECTED",this.onPageFirstClicked);
            ExternalInterface.addCallback("PAGE_LEFT_SELECTED",this.onPageLeftClicked);
            ExternalInterface.addCallback("PAGE_ME_SELECTED",this.onPageMeClicked);
            ExternalInterface.addCallback("PAGE_RIGHT_SELECTED",this.onPageRightClicked);
            ExternalInterface.addCallback("ON_FILTER_CHANGED",this.onFilterButtonToggleController);
         }
         else
         {
            this.setRewardInfo(0,"rewardId_0","",100,1,100,-1);
            this.setRewardInfo(1,"rewardId_1","",50,1,200,-1);
            this.setRewardInfo(2,"rewardId_2","",-1,0.23,300,-1);
            this.setRewardInfo(3,"rewardId_3","",-1,0,300,1000);
            this.setRewardInfo(4,"rewardId_4","",9999,0,300,5000);
            _loc2_ = 0;
            while(_loc2_ < 3)
            {
               this.addCategory(_loc2_,"Test" + _loc2_);
               _loc2_++;
            }
            _loc2_ = 0;
            while(_loc2_ < 10)
            {
               this.addLeaderboard(0,_loc2_,"","","",0,_loc2_ == 1);
               _loc2_++;
            }
            _loc2_ = 0;
            while(_loc2_ < 10)
            {
               this.addLeaderboardEntry(0,"TestName" + _loc2_,_loc2_ + 1,1000 - _loc2_,false,false);
               _loc2_++;
            }
         }
         this.categoryView.setItemPadding(0);
         this.leaderboardView.vertScrollbarVisible = false;
         this.leaderboardView.setItemPadding(-1);
         this.leaderboardView.windowPaddingX = 0;
         this.leaderboardView.windowPaddingY = 0;
         this.leaderboardFooterMC.btnPageFirst.addEventListener(MouseEvent.CLICK,this.onPageFirstClicked,false,0,true);
         this.leaderboardFooterMC.btnPageLeft.addEventListener(MouseEvent.CLICK,this.onPageLeftClicked,false,0,true);
         this.leaderboardFooterMC.btnPageMe.addEventListener(MouseEvent.CLICK,this.onPageMeClicked,false,0,true);
         this.leaderboardFooterMC.btnPageRight.addEventListener(MouseEvent.CLICK,this.onPageRightClicked,false,0,true);
         this.leaderboardFooterMC.playerScoreMC.visible = false;
         this.leaderboardHeaderMC.filtersMC.everyoneRadioBtn.addEventListener(Event.CHANGE,this.cloned_onEveryoneFilterChanged,false,0,true);
         this.leaderboardHeaderMC.filtersMC.friendsRadioBtn.addEventListener(Event.CHANGE,this.cloned_onFriendsFilterChanged,false,0,true);
         this.leaderboardHeaderMC.favoriteCheckbox.addEventListener(Event.CHANGE,this.cloned_onFavoriteChanged,false,0,true);
         this.leaderboardHeaderMC.favoriteCheckbox.textField.visible = false;
         this.sectionCategorySelectHighlight.visible = false;
         this.sectionFiltersSelectHighlight.visible = false;
         this.sectionRewardsSelectHighlight.visible = false;
         this.currentFilterHighlight = this.leaderboardHeaderMC.everyoneRadioBtnHighlight;
         this.leaderboardHeaderMC.everyoneRadioBtnHighlight.visible = false;
         this.leaderboardHeaderMC.friendsRadioBtnHighlight.visible = false;
         this.leaderboardHeaderMC.favoriteButtonHighlight.visible = false;
         this.leaderboardFooterMC.btnPageFirstHighlight.visible = false;
         this.leaderboardFooterMC.btnPageLeftHighlight.visible = false;
         this.leaderboardFooterMC.btnPageMeHighlight.visible = false;
         this.leaderboardFooterMC.btnPageRightHighlight.visible = false;
         this.leaderboardHeaderMC.everyoneRadioBtnHighlight.addChild(new DirectionalMapping(null,this.leaderboardHeaderMC.friendsRadioBtnHighlight,this.leaderboardFooterMC.btnPageFirstHighlight,null));
         this.leaderboardHeaderMC.friendsRadioBtnHighlight.addChild(new DirectionalMapping(null,this.leaderboardHeaderMC.favoriteButtonHighlight,this.leaderboardFooterMC.btnPageFirstHighlight,this.leaderboardHeaderMC.everyoneRadioBtnHighlight));
         this.leaderboardHeaderMC.favoriteButtonHighlight.addChild(new DirectionalMapping(null,null,this.leaderboardFooterMC.btnPageFirstHighlight,this.leaderboardHeaderMC.friendsRadioBtnHighlight));
         this.leaderboardFooterMC.btnPageFirstHighlight.addChild(new DirectionalMapping(this.leaderboardHeaderMC.everyoneRadioBtnHighlight,this.leaderboardFooterMC.btnPageLeftHighlight,null,null));
         this.leaderboardFooterMC.btnPageLeftHighlight.addChild(new DirectionalMapping(this.leaderboardHeaderMC.everyoneRadioBtnHighlight,this.leaderboardFooterMC.btnPageMeHighlight,null,this.leaderboardFooterMC.btnPageFirstHighlight));
         this.leaderboardFooterMC.btnPageMeHighlight.addChild(new DirectionalMapping(this.leaderboardHeaderMC.everyoneRadioBtnHighlight,this.leaderboardFooterMC.btnPageRightHighlight,null,this.leaderboardFooterMC.btnPageLeftHighlight));
         this.leaderboardFooterMC.btnPageRightHighlight.addChild(new DirectionalMapping(this.leaderboardHeaderMC.everyoneRadioBtnHighlight,null,null,this.leaderboardFooterMC.btnPageMeHighlight));
         this.setupTranslation();
         this.ghInit();
         var _loc1_:TextField = this.contestRewardsMC.contest.contestEndsText as TextField;
         if(_loc1_)
         {
            if(_loc1_.numLines > 1)
            {
               _loc1_.y = 25;
            }
         }
      }

      public function onCategoryHeadingClick(param1:BagContainerBasic) : void
      {
         if(!IggyFunctions.inIggy)
         {
         }
         this.refreshLayout();
      }

      public function refreshLayout() : void
      {
         this.categoryView.refreshLayout();
      }

      private function addCategory(param1:int, param2:String) : void
      {
         this.ghCategories[param1] = IggyFunctions.translate(param2);
         var _loc3_:BagContainerBasic = new BagContainerBasic(this.onCategoryHeadingClick,param1,0,0);
         _loc3_.maxRowCount = 3;
         _loc3_.windowPaddingX = 40;
         _loc3_.footerPaddingY = -17;
         _loc3_.heading.allowFontResize = true;
         _loc3_.category = param2;
         _loc3_.collapsedIcon.mouseEnabled = false;
         _loc3_.collapsedIcon.mouseChildren = false;
         if(!IsConsole())
         {
            _loc3_.collapsed = this.addedCategories > 0;
         }
         else
         {
            _loc3_.collapsed = true;
         }
         ++this.addedCategories;
         this.categoryBags[param1] = _loc3_;
         _loc3_.addEventListener("CATEGORY_TOGGLED",this.onCategoryToggled);
         this.categoryView.addItem(_loc3_);
      }

      public function onCategoryToggled(param1:MouseEvent) : void
      {
         var _loc2_:int = int(param1.currentTarget.id);
         if(_loc2_ != this.currentCategory)
         {
            this.setCategory(_loc2_);
         }
      }

      public function setCategory(param1:int) : *
      {
         var _loc2_:BagContainerBasic = null;
         this.currentCategory = param1;
         for each(_loc2_ in this.categoryBags)
         {
            if(_loc2_.id == param1 && !_loc2_.collapsed)
            {
               _loc2_.collapsed = false;
            }
            else
            {
               _loc2_.collapsed = true;
            }
         }
         this.refreshLayout();
      }

      private function getCategory(param1:uint) : BagContainerBasic
      {
         return this.categoryBags[param1];
      }

      private function getLeaderboardInfo(param1:Number) : LeaderboardInfo
      {
         return this.leaderboardInfos[param1];
      }

      private function addLeaderboard(param1:int, param2:Number, param3:String, param4:String, param5:String, param6:int, param7:Boolean) : void
      {
         this.ghAddBoard(param1,param2,param3,param4,param5,param6,param7);
         this.addLeaderboardInfo(param2,param3,param6);
         var _loc8_:SlotBasic = this.getCategory(param1).addSlot(param2,param3,param5);
         _loc8_.clickFeedback = true;
         _loc8_.slotImageSize = 51;
         _loc8_.equippedIndex = 3;
         _loc8_.tooltipName = param3;
         _loc8_.tooltipDescription = param4;
         _loc8_.tooltipMinWidth = 160;
         if(!IsConsole())
         {
            if(param7 && this.currentLeaderboard == -1)
            {
               this.setCategory(param1);
               ExternalInterface.call("SetLeaderboard",param2);
            }
         }
         if(this.currentCategory == param1)
         {
            this.refreshLayout();
         }
      }

      private function removeLeaderboard(param1:int, param2:Number) : void
      {
         this.removeLeaderboardInfo(param2);
         this.getCategory(param1).removeSlot(param2);
         this.refreshLayout();
      }

      private function addLeaderboardInfo(param1:Number, param2:String, param3:int) : void
      {
         var _loc4_:LeaderboardInfo = this.getLeaderboardInfo(param1);
         if(_loc4_ == null)
         {
            _loc4_ = new LeaderboardInfo(param2,param3);
            this.leaderboardInfos[param1] = _loc4_;
         }
         ++_loc4_.refCount;
      }

      private function removeLeaderboardInfo(param1:Number) : void
      {
         var _loc2_:LeaderboardInfo = this.getLeaderboardInfo(param1);
         if(_loc2_ != null)
         {
            --_loc2_.refCount;
            if(_loc2_.refCount <= 0)
            {
               this.leaderboardInfos.splice(param1,1);
            }
         }
      }

      private function setLeaderboardInfo(param1:Number, param2:int, param3:Boolean, param4:int, param5:Number) : void
      {
         var _loc9_:TextFormat = null;
         this.setLoading(false);
         var _loc6_:Boolean = param4 > 0;
         this.leaderboardView.clear();
         var _loc7_:TextField = this.leaderboardHeaderMC.leaderboardName as TextField;
         var _loc8_:TextFormat = new TextFormat(null,16);
         _loc7_.setTextFormat(_loc8_);
         _loc7_.text = this.getLeaderboardInfo(param1).name;
         if(_loc7_.textWidth > _loc7_.width || _loc7_.numLines > 1)
         {
            _loc9_ = new TextFormat(null,14);
            _loc7_.setTextFormat(_loc9_);
         }
         this.numEntries = param2;
         if(this.ghWaiting && param1 == this.ghBoard)
         {
            this.ghWaiting = false;
            this.ghTimer.reset();
            if(param2 <= 0)
            {
               this.ghStatus.text = "Empty board " + param1;
               if(this.ghAuto) this.ghNextBoard();
               return;
            }
            this.ghStartBoard(param2);
            return;
         }
         this.leaderboardHeaderMC.favoriteCheckbox.checked = param3;
         this.leaderboardFooterMC.playerScoreMC.visible = _loc6_;
         this.leaderboardFooterMC.playerScoreMC.score.text = this.formatRank(param4);
         this.leaderboardFooterMC.btnPageMe.enabled = _loc6_ && param2 > this.ITEMS_PER_PAGE;
         if(param2 > 0)
         {
            if(_loc6_)
            {
               this.getPageResultsNearPlayer();
            }
            else
            {
               this.getFirstPageResults();
            }
         }
         else
         {
            this.entryIndex = 1;
         }
      }

      private function setLeaderboard(param1:Number, param2:Boolean) : void
      {
         if((this.ghRunning || this.ghWaiting || this.ghAdvancing) && param1 != this.ghBoard)
         {
            this.ghFail("Board changed; stopped");
         }
         this.setLoading(true);
         this.cloned_clearSelected();
         this.cloned_setSelected(this.currentCategory,param1);
         this.currentLeaderboard = param1;
         if(!param2)
         {
            this.leaderboardHeaderMC.filtersMC.everyoneRadioBtn.checked = true;
            this.leaderboardHeaderMC.filtersMC.friendsRadioBtn.checked = false;
         }
         this.leaderboardHeaderMC.filtersMC.visible = param2;
         this.leaderboardHeaderMC.pagesTxt.visible = param2;
      }

      private function addLeaderboardEntry(param1:Number, param2:String, param3:int, param4:Number, param5:Boolean, param6:Boolean) : void
      {
         if(this.ghRunning && param1 == this.ghBoard)
         {
            this.ghEntry(param1,param2,param3,param4,param5,param6);
            return;
         }
         if(this.entryIndex == 0)
         {
            this.entryIndex = param3;
         }
         var _loc7_:MovieClip = new LeaderboardEntry();
         _loc7_.txt_rank.text = this.formatRank(param3);
         _loc7_.txt_userName.text = param2;
         _loc7_.txt_time.text = this.formatScore(param4,this.getLeaderboardInfo(param1).displayType);
         _loc7_.friendIcon.visible = param5 || param6;
         if(param5)
         {
            _loc7_.friendIcon.gotoAndStop("friend");
         }
         this.leaderboardView.addItem(_loc7_);
         this.setLoading(false);
      }

      private function updateRewardDisplayOrder(param1:Boolean) : void
      {
         this.contestRewardsMC.setDisplayOrder(param1);
      }

      private function setRewardInfo(param1:int, param2:String, param3:String, param4:int, param5:Number, param6:Number, param7:int) : void
      {
         var _loc8_:String = null;
         var _loc9_:String = null;
         if(param7 <= 0)
         {
            _loc8_ = "$Leaderboard_YourScore";
            _loc9_ = int(param6) + "+";
         }
         else
         {
            _loc8_ = "$Leaderboard_YourRank";
            _loc9_ = int(param7).toString();
            if(param7 > 1)
            {
               _loc9_ += "+";
            }
         }
         this.contestRewardsMC.setReward(param1,param2,param3,param4,_loc8_,_loc9_,param5);
      }

      private function clearRewardInfos() : void
      {
         this.contestRewardsMC.clearRewards();
      }

      private function setTimeUntilReset(param1:Number) : void
      {
         this.contestRewardsMC.setTimeUntilReset(param1);
      }

      private function setMaxEarnedReward(param1:int) : void
      {
         this.contestRewardsMC.setMaxEarnedReward(param1);
      }

      private function getEntriesRangeFailed() : void
      {
         if(this.ghRunning) this.ghFail("Request failed");
         this.setLoading(false);
      }

      private function getEntriesNearPlayerFailed() : void
      {
         this.setLoading(false);
      }

      private function setLeaderboardFailed() : void
      {
         this.setLoading(false);
      }

      private function getPageResults() : void
      {
         this.setLoading(true);
         this.leaderboardView.clear();
         ExternalInterface.call("GetEntriesRange",this.currentLeaderboard,this.entryIndex,this.entryIndex + this.resultsOnPage);
      }

      private function getFirstPageResults() : void
      {
         this.entryIndex = 1;
         this.getPageResults();
      }

      private function getPageResultsNearPlayer() : void
      {
         this.setLoading(true);
         this.entryIndex = 0;
         this.leaderboardView.clear();
         ExternalInterface.call("GetEntriesNearPlayer",this.currentLeaderboard,this.ITEMS_PER_PAGE);
      }

      private function setLoading(param1:Boolean) : void
      {
         this.loadingMC.visible = param1;
         this.leaderboardFooterMC.mouseEnabled = !param1;
         this.leaderboardFooterMC.mouseChildren = !param1;
         this.categoryView.mouseEnabled = !param1;
         this.categoryView.mouseChildren = !param1;
         this.leaderboardHeaderMC.mouseEnabled = !param1;
         this.leaderboardHeaderMC.mouseChildren = !param1;
      }

      private function formatScore(param1:Number, param2:int) : String
      {
         var _loc3_:NumberFormat = new NumberFormat();
         if(param2 == LeaderboardInfo.SCORE_DISPLAY_TYPE_INTEGER)
         {
            _loc3_.fractionalDigits = 0;
            return _loc3_.formatNumber(param1);
         }
         if(param2 == LeaderboardInfo.SCORE_DISPLAY_TYPE_FLOATING_POINT)
         {
            _loc3_.fractionalDigits = 2;
            _loc3_.trailingZeros = true;
            return _loc3_.formatNumber(param1);
         }
         return "";
      }

      private function formatRank(param1:int) : String
      {
         return this.formatScore(Number(param1),LeaderboardInfo.SCORE_DISPLAY_TYPE_INTEGER);
      }

      private function onPageFirstClicked(param1:MouseEvent) : void
      {
         if(this.leaderboardFooterMC.btnPageFirst.enabled)
         {
            this.getFirstPageResults();
         }
      }

      private function onPageLeftClicked(param1:MouseEvent) : void
      {
         if(this.leaderboardFooterMC.btnPageLeft.enabled)
         {
            this.entryIndex = Math.max(this.entryIndex - this.ITEMS_PER_PAGE,1);
            this.getPageResults();
         }
      }

      private function onPageMeClicked(param1:MouseEvent) : void
      {
         if(this.leaderboardFooterMC.btnPageMe.enabled)
         {
            this.getPageResultsNearPlayer();
         }
      }

      private function onPageRightClicked(param1:MouseEvent) : void
      {
         if(this.leaderboardFooterMC.btnPageRight.enabled)
         {
            this.entryIndex = Math.min(this.entryIndex + this.ITEMS_PER_PAGE,this.lastPageIndex + 1);
            this.getPageResults();
         }
      }

      private function onPageLastClicked(param1:MouseEvent) : void
      {
         this.entryIndex = this.lastPageIndex;
         this.getPageResults();
      }

      protected function onFriendsFilterChanged(param1:Event) : void
      {
         var _loc2_:RadioButton = RadioButton(param1.target);
         if(_loc2_.checked)
         {
            ExternalInterface.call("SetFilter",FILTER_FRIENDS);
            ExternalInterface.call("SetLeaderboard",this.currentLeaderboard);
         }
      }

      protected function onEveryoneFilterChanged(param1:Event) : void
      {
         var _loc2_:RadioButton = RadioButton(param1.target);
         if(_loc2_.checked)
         {
            ExternalInterface.call("SetFilter",FILTER_EVERYONE);
            ExternalInterface.call("SetLeaderboard",this.currentLeaderboard);
         }
      }

      private function onFilterButtonToggleController() : void
      {
         var _loc5_:Boolean = false;
         var _loc6_:Array = null;
         var _loc7_:int = 0;
         var _loc1_:Array = [this.leaderboardFooterMC.btnPageFirstHighlight,this.leaderboardFooterMC.btnPageLeftHighlight,this.leaderboardFooterMC.btnPageMeHighlight,this.leaderboardFooterMC.btnPageRightHighlight];
         var _loc2_:* = _loc1_.indexOf(this.currentFilterHighlight);
         var _loc3_:Array = [this.leaderboardHeaderMC.everyoneRadioBtnHighlight,this.leaderboardHeaderMC.friendsRadioBtnHighlight];
         var _loc4_:int = _loc3_.indexOf(this.currentFilterHighlight);
         if(_loc2_ != -1)
         {
            if(_loc2_ == 0)
            {
               this.onPageFirstClicked(MouseEvent(MouseEvent.CLICK));
            }
            else if(_loc2_ == 1)
            {
               this.onPageLeftClicked(MouseEvent(MouseEvent.CLICK));
            }
            else if(_loc2_ == 2)
            {
               this.onPageMeClicked(MouseEvent(MouseEvent.CLICK));
            }
            else if(_loc2_ == 3)
            {
               this.onPageRightClicked(MouseEvent(MouseEvent.CLICK));
            }
         }
         else if(_loc4_ == -1)
         {
            this.leaderboardHeaderMC.favoriteCheckbox.checked = !this.leaderboardHeaderMC.favoriteCheckbox.checked;
            _loc5_ = Boolean(this.leaderboardHeaderMC.favoriteCheckbox.checked);
            ExternalInterface.call("SetFavorite",this.currentLeaderboard,_loc5_);
         }
         else
         {
            _loc6_ = [this.leaderboardHeaderMC.filtersMC.everyoneRadioBtn,this.leaderboardHeaderMC.filtersMC.friendsRadioBtn];
            _loc7_ = 0;
            while(_loc7_ < _loc6_.length)
            {
               _loc6_[_loc7_].checked = _loc7_ == _loc4_;
               _loc7_++;
            }
            ExternalInterface.call("SetFilter",_loc4_);
            ExternalInterface.call("SetLeaderboard",this.currentLeaderboard);
         }
      }

      protected function onFavoriteChanged(param1:Event) : void
      {
         var _loc2_:Boolean = Boolean(this.leaderboardHeaderMC.favoriteCheckbox.checked);
         ExternalInterface.call("SetFavorite",this.currentLeaderboard,_loc2_);
      }

      protected function clearSelected() : void
      {
         var _loc1_:BagContainerBasic = null;
         for each(_loc1_ in this.categoryBags)
         {
            _loc1_.unequipAllSlots();
         }
      }

      protected function setSelected(param1:int, param2:Number) : void
      {
         var _loc4_:SlotBasic = null;
         var _loc3_:BagContainerBasic = this.getCategory(param1);
         if(_loc3_)
         {
            _loc4_ = _loc3_.getSlotById(param2);
            if(_loc4_)
            {
               _loc4_.equipped = true;
            }
         }
      }

      private function getConfigured() : void
      {
         ExternalInterface.call("LEADERBOARDS.CONFIGURED",this.SLOTS_PER_ROW);
      }

      private function highlightCategory(param1:int) : void
      {
         var _loc3_:GlowFilter = null;
         var _loc4_:Array = null;
         var _loc2_:MovieClip = this.categoryBags[param1] as MovieClip;
         if(_loc2_)
         {
            this.setScrollLocation(_loc2_,param1);
            _loc3_ = new GlowFilter();
            _loc3_.blurX = _loc3_.blurY = 2;
            _loc3_.color = 13434624;
            _loc3_.inner = true;
            _loc3_.quality = BitmapFilterQuality.HIGH;
            _loc3_.strength = 100;
            _loc4_ = new Array();
            _loc4_.push(_loc3_);
            _loc2_.heading.filters = _loc4_;
            if(IsNX())
            {
               _loc2_.highlight.visible = true;
            }
         }
      }

      private function unhighlightCategory(param1:int) : void
      {
         var _loc3_:Array = null;
         var _loc2_:MovieClip = this.categoryBags[param1] as MovieClip;
         if(_loc2_)
         {
            _loc3_ = new Array();
            _loc2_.heading.filters = _loc3_;
            if(IsNX())
            {
               _loc2_.highlight.visible = false;
            }
         }
      }

      private function switchCategory(param1:int) : void
      {
         var _loc2_:BagContainerBasic = this.categoryBags[param1];
         if(_loc2_)
         {
            _loc2_.collapsed = !_loc2_.collapsed;
            this.onCategoryHeadingClick(_loc2_);
            _loc2_.dispatchEvent(new MouseEvent("CATEGORY_TOGGLED"));
         }
      }

      private function highlightSlot(param1:int, param2:int) : void
      {
         var _loc4_:Point = null;
         var _loc5_:int = 0;
         var _loc3_:SlotBasic = this.categoryBags[param1].getSlotById(param2);
         if(_loc3_)
         {
            this.setScrollLocation(_loc3_ as MovieClip,param1);
            _loc4_ = _loc3_.localToGlobal(new Point(_loc3_.width / 2,_loc3_.height / 2));
            _loc5_ = this.categoryView.scrollV * this.categoryView.verticalStep;
            _loc3_.showTooltipAt(root.x + root.width + TOOLTIP_PADDING,localToGlobal(new Point(this.contestRewardsMC.x,this.contestRewardsMC.y)).y);
            if(_loc3_.bkgrd)
            {
               _loc3_.bkgrd.gotoAndStop("active");
            }
            if(_loc3_.bkgrdLocked)
            {
               _loc3_.bkgrdLocked.gotoAndStop("active");
            }
         }
      }

      private function unhighlightSlot(param1:int, param2:int) : void
      {
         var _loc3_:SlotBasic = this.categoryBags[param1].getSlotById(param2);
         if(_loc3_)
         {
            _loc3_.handleRollOut();
            if(_loc3_.bkgrd)
            {
               _loc3_.bkgrd.gotoAndStop("inactive");
            }
            if(_loc3_.bkgrdLocked)
            {
               _loc3_.bkgrdLocked.gotoAndStop("inactive");
            }
         }
      }

      private function activateSlot(param1:int, param2:int) : void
      {
         var _loc3_:SlotBasic = this.categoryBags[param1].getSlotById(param2);
         if(_loc3_)
         {
            _loc3_.activate();
            this.highlightSlot(param1,param2);
         }
      }

      private function setScrollLocation(param1:MovieClip, param2:int) : void
      {
         var _loc4_:BagContainerBasic = null;
         var _loc5_:Number = NaN;
         var _loc3_:Number = 2 * this.categoryView.windowPaddingY;
         for each(_loc4_ in this.categoryBags)
         {
            _loc3_ += _loc4_.height;
         }
         _loc5_ = this.categoryView.viewportMovieClip.height - this.categoryView.height;
         if(_loc5_ <= 0)
         {
            return;
         }
         var _loc6_:Number = 2 * this.categoryView.windowPaddingY + this.categoryBags[param2].heading.getBounds(this.categoryView).height;
         var _loc7_:Number = (param1.getBounds(this.categoryView).y - _loc6_) / _loc5_;
         this.categoryView.scrollV = _loc7_ * this.categoryView.maxScrollV;
      }

      private function collapseCategory(param1:int) : void
      {
         var _loc2_:BagContainerBasic = null;
         for each(_loc2_ in this.categoryBags)
         {
            _loc2_.collapsed = true;
         }
         this.refreshLayout();
      }

      private function switchSections(param1:Number, param2:Number) : *
      {
         if(param1 != -1)
         {
            switch(param1)
            {
               case 0:
                  this.sectionCategorySelectHighlight.visible = false;
                  break;
               case 1:
                  this.sectionFiltersSelectHighlight.visible = false;
                  this.currentFilterHighlight.visible = false;
                  break;
               case 2:
                  this.sectionRewardsSelectHighlight.visible = false;
            }
         }
         if(param2 != -1)
         {
            switch(param2)
            {
               case 0:
                  this.sectionCategorySelectHighlight.visible = true;
                  break;
               case 1:
                  this.sectionFiltersSelectHighlight.visible = true;
                  this.currentFilterHighlight = this.leaderboardHeaderMC.everyoneRadioBtnHighlight;
                  if(this.leaderboardHeaderMC.filtersMC.visible == true)
                  {
                     this.currentFilterHighlight.visible = true;
                  }
                  break;
               case 2:
                  this.sectionRewardsSelectHighlight.visible = true;
            }
         }
      }

      private function moveFiltersCursor(param1:int, param2:int) : void
      {
         var _loc4_:MovieClip = null;
         var _loc5_:* = undefined;
         var _loc3_:DirectionalMapping = this.currentFilterHighlight.getChildByName(DirectionalMapping.CHILD_NAME) as DirectionalMapping;
         if(_loc3_)
         {
            _loc4_ = _loc3_.getAdjacent(param1,param2);
            if(_loc4_)
            {
               _loc5_ = this.currentFilterHighlight.visible;
               this.currentFilterHighlight.visible = false;
               this.currentFilterHighlight = _loc4_;
               if(_loc5_)
               {
                  this.currentFilterHighlight.visible = true;
               }
            }
         }
      }

      private function moveRewardsCursor(param1:Number, param2:Number) : *
      {
         var _loc3_:MovieClip = null;
         var _loc4_:MovieClip = null;
         if(param1 != -1)
         {
            _loc3_ = this.contestRewardsMC.rewardTiles[param1];
            _loc3_.contestSelectHighlight.visible = false;
            _loc3_.iconMC.handleRollOut();
         }
         if(param2 != -1)
         {
            _loc4_ = this.contestRewardsMC.rewardTiles[param2];
            _loc4_.contestSelectHighlight.visible = true;
            _loc4_.iconMC.showTooltipAt(root.x + root.width + TOOLTIP_PADDING,localToGlobal(new Point(this.contestRewardsMC.x,this.contestRewardsMC.y)).y);
         }
      }

      internal function __setProp_winHeader_Scene1_header_0() : *
      {
         try
         {
            this.winHeader["componentInspectorSetting"] = true;
         }
         catch(e:Error)
         {
         }
         this.winHeader.enabled = false;
         this.winHeader.title = "$Leaderboard_Header";
         this.winHeader.visible = true;
         try
         {
            this.winHeader["componentInspectorSetting"] = false;
         }
         catch(e:Error)
         {
         }
      }

      internal function frame1() : *
      {
         stop();
      }

      internal function frame11() : *
      {
         stop();
         this.leaderboardHeaderMC.gotoAndPlay("Console");
         this.leaderboardView.gotoAndPlay("Console");
         this.leaderboardFooterMC.gotoAndPlay("Console");
         this.loadingMC.gotoAndPlay("Console");
         this.contestRewardsMC.gotoAndPlay("Console");
      }

      private function cloned_onEveryoneFilterChanged(param1:Event) : void
      {
         var _loc2_:RadioButton = RadioButton(param1.target);
         if(_loc2_.checked)
         {
            ExternalInterface.call("SetFilter",FILTER_EVERYONE);
            ExternalInterface.call("SetLeaderboard",this.currentLeaderboard);
         }
      }

      private function cloned_onFriendsFilterChanged(param1:Event) : void
      {
         var _loc2_:RadioButton = RadioButton(param1.target);
         if(_loc2_.checked)
         {
            ExternalInterface.call("SetFilter",FILTER_FRIENDS);
            ExternalInterface.call("SetLeaderboard",this.currentLeaderboard);
         }
      }

      private function cloned_onFavoriteChanged(param1:Event) : void
      {
         var _loc2_:Boolean = Boolean(this.leaderboardHeaderMC.favoriteCheckbox.checked);
         ExternalInterface.call("SetFavorite",this.currentLeaderboard,_loc2_);
      }

      private function cloned_clearSelected() : void
      {
         var _loc1_:BagContainerBasic = null;
         for each(_loc1_ in this.categoryBags)
         {
            _loc1_.unequipAllSlots();
         }
      }

      private function cloned_setSelected(param1:int, param2:Number) : void
      {
         var _loc4_:SlotBasic = null;
         var _loc3_:BagContainerBasic = this.getCategory(param1);
         if(_loc3_)
         {
            _loc4_ = _loc3_.getSlotById(param2);
            if(_loc4_)
            {
               _loc4_.equipped = true;
            }
         }
      }


      private function ghInit() : void
      {
         if(!IggyFunctions.inIggy) return;
         this.ghTimer.addEventListener(TimerEvent.TIMER,this.ghTick);
         var toggle:Sprite = this.ghButton("Collector",680,54,145,this.ghToggle);
         addChild(toggle);
         this.ghPanel = new Sprite();
         this.ghPanel.x = 680;
         this.ghPanel.y = 78;
         this.ghPanel.graphics.beginFill(0x101c2b,0.96);
         this.ghPanel.graphics.drawRect(0,0,145,130);
         this.ghPanel.graphics.endFill();
         this.ghPanel.addChild(this.ghButton("1. Catalog",5,5,135,this.ghSaveCatalog));
         this.ghPanel.addChild(this.ghButton("2. Current board",5,29,135,this.ghOne));
         this.ghPanel.addChild(this.ghButton("3. All boards",5,53,135,this.ghAll));
         this.ghPanel.addChild(this.ghButton("Reset / Stop",5,77,135,this.ghReset));
         this.ghStatus = new TextField();
         this.ghStatus.defaultTextFormat = new TextFormat("_sans",10,0xffffff);
         this.ghStatus.width = 135; this.ghStatus.height = 24;
         this.ghStatus.x = 5; this.ghStatus.y = 102;
         this.ghStatus.selectable = false; this.ghStatus.text = "Ready";
         this.ghPanel.addChild(this.ghStatus);
         this.ghPanel.visible = false;
         addChild(this.ghPanel);
      }

      private function ghButton(label:String, px:int, py:int, width:int, fn:Function) : Sprite
      {
         var button:Sprite = new Sprite();
         button.x = px; button.y = py; button.buttonMode = true; button.mouseChildren = false;
         button.graphics.beginFill(0x324c63); button.graphics.drawRect(0,0,width,20); button.graphics.endFill();
         var text:TextField = new TextField();
         text.defaultTextFormat = new TextFormat("_sans",11,0xffffff,true);
         text.width = width; text.height = 20; text.selectable = false; text.text = label;
         button.addChild(text); button.addEventListener(MouseEvent.CLICK,fn);
         return button;
      }
      private function ghToggle(e:MouseEvent) : void { e.stopPropagation(); this.ghPanel.visible = !this.ghPanel.visible; }
      private function ghLoadConfig(key:String, value:String) : void
      {
         if(key == "leaderboard_ids") this.ghConfigIds = value;
         if(key == "leaderboard_progress") this.ghProgress = value;
      }
      private function ghClean(value:String) : String
      {
         if(value == null) return "";
         return value.split("\t").join(" ").split("\r").join(" ").split("\n").join(" ").split("||").join(" ");
      }
      private function ghAddBoard(category:int, id:Number, key:String, description:String, icon:String, type:int, def:Boolean) : void
      {
         var display:String = IggyFunctions.translate(key);
         var categoryName:String = this.ghCategories[category] as String;
         this.ghCatalog += "||leaderboard\t" + category + "\t" + this.ghClean(categoryName) + "\t" + id + "\t" + this.ghClean(key) + "\t" + this.ghClean(description) + "\t" + this.ghClean(icon) + "\t" + type + "\t" + def + "\t" + this.ghClean(display);
         if(this.ghIds.indexOf(id) < 0) this.ghIds.push(id);
      }
      private function ghSaveCatalog(e:MouseEvent) : void
      {
         e.stopPropagation();
         var ids:String = this.ghIds.join(",");
         var meta:String = "entries=" + this.ghIds.length + ";complete=true;savedAt=" + new Date().time;
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_catalog",this.ghCatalog);
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_catalog_meta",meta);
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_ids",ids);
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_ids_meta",meta);
         this.ghConfigIds = ids;
         this.ghStatus.text = "Catalog: " + this.ghIds.length + " boards";
      }
      private function ghOne(e:MouseEvent) : void
      {
         e.stopPropagation();
         if(this.ghRunning || this.ghWaiting || this.ghAdvancing) { this.ghStatus.text = "Already running"; return; }
         if(this.currentLeaderboard < 0 || this.numEntries <= 0) { this.ghStatus.text = "Select a board first"; return; }
         this.ghAuto = false; this.ghBoard = this.currentLeaderboard;
         this.ghStart = 0; this.ghRun = "";
         this.ghFilterEveryone(); this.ghLock(true); this.ghWaitForBoard();
      }
      private function ghAll(e:MouseEvent) : void
      {
         e.stopPropagation();
         if(this.ghRunning || this.ghWaiting || this.ghAdvancing) { this.ghStatus.text = "Already running"; return; }
         var saved:String = this.ghConfigIds || this.ghIds.join(",");
         if(!saved) { this.ghStatus.text = "Save catalog first"; return; }
         this.ghIds = saved.split(",");
         this.ghBoardIndex = 0; this.ghStart = 0; this.ghRun = "";
         var last:String = this.ghProgressValue("leaderboard");
         if(last)
         {
            var i:int = this.ghIds.indexOf(last);
            if(i >= 0)
            {
               this.ghBoardIndex = i;
               if(this.ghProgressValue("complete") == "true") this.ghBoardIndex++;
               else { this.ghStart = int(this.ghProgressValue("end")) + 1; this.ghRun = this.ghProgressValue("run"); }
            }
         }
         this.ghAuto = true; this.ghFilterEveryone(); this.ghLock(true); this.ghLoadBoard();
      }
      private function ghLoadBoard() : void
      {
         if(this.ghBoardIndex >= this.ghIds.length) { this.ghAuto = false; this.ghLock(false); this.ghStatus.text = "All boards complete"; return; }
         this.ghBoard = Number(this.ghIds[this.ghBoardIndex]);
         this.ghWaitForBoard();
      }
      private function ghLock(locked:Boolean) : void
      {
         this.categoryView.mouseEnabled = !locked; this.categoryView.mouseChildren = !locked;
         this.leaderboardHeaderMC.mouseEnabled = !locked; this.leaderboardHeaderMC.mouseChildren = !locked;
         this.leaderboardFooterMC.mouseEnabled = !locked; this.leaderboardFooterMC.mouseChildren = !locked;
      }
      private function ghFilterEveryone() : void
      {
         this.leaderboardHeaderMC.filtersMC.everyoneRadioBtn.checked = true;
         this.leaderboardHeaderMC.filtersMC.friendsRadioBtn.checked = false;
         ExternalInterface.call("SetFilter",FILTER_EVERYONE);
      }
      private function ghWaitForBoard() : void
      {
         this.ghStatus.text = "Loading board " + this.ghBoard;
         this.ghWaiting = true; this.ghTimer.reset(); this.ghTimer.delay = 8000; this.ghTimer.start();
         ExternalInterface.call("SetLeaderboard",this.ghBoard);
      }
      private function ghStartBoard(total:int) : void
      {
         this.ghRunning = true; this.ghTotal = total; this.ghSaved = this.ghStart;
         if(!this.ghRun) this.ghRun = this.ghBoard + "_" + new Date().time;
         this.ghRequest();
      }
      private function ghRequest() : void
      {
         if(!this.ghRunning) return;
         if(this.ghStart >= this.ghTotal) { this.ghFail("Resume beyond board size"); return; }
         this.ghEnd = Math.min(this.ghStart + 899,this.ghTotal - 1);
         this.ghWanted = this.ghEnd - this.ghStart + 1; this.ghCount = 0;
         this.ghRows = "rank\tname\tscore\tscoreType\tscoreName\tisCurrentPlayer\tisFriend";
         this.ghStatus.text = "Board " + this.ghBoard + " " + (this.ghStart + 1) + "/" + this.ghTotal;
         this.ghTimer.reset(); this.ghTimer.delay = 8000; this.ghTimer.start();
         ExternalInterface.call("GetEntriesRange",this.ghBoard,this.ghStart,this.ghEnd);
      }
      private function ghEntry(board:Number, name:String, rank:int, score:Number, friend:Boolean, player:Boolean) : void
      {
         var info:LeaderboardInfo = this.getLeaderboardInfo(board);
         var scoreName:String = info ? info.name : "";
         this.ghRows += "||" + rank + "\t" + this.ghClean(name) + "\t" + score + "\t" + board + "\t" + this.ghClean(scoreName) + "\t" + player + "\t" + friend;
         this.ghCount++; this.ghSaved++;
         this.ghTimer.reset(); this.ghTimer.delay = 8000; this.ghTimer.start();
         if(this.ghCount >= this.ghWanted)
         {
            this.ghTimer.reset();
            var complete:Boolean = this.ghEnd >= this.ghTotal - 1;
            this.ghSaveBatch(complete);
            this.ghRunning = false; this.ghAdvancing = true;
            this.ghTimer.delay = 500; this.ghTimer.start();
         }
      }
      private function ghSaveBatch(complete:Boolean) : void
      {
         var meta:String = "leaderboard=" + this.ghBoard + ";leaderboardId=" + this.ghBoard + ";run=" + this.ghRun + ";start=" + this.ghStart + ";end=" + this.ghEnd + ";entries=" + this.ghCount + ";saved=" + this.ghSaved + ";expected=" + this.ghTotal + ";complete=" + complete + ";cleared=false;savedAt=" + new Date().time + ";rowSep=||;fieldSep=tab";
         this.ghProgress = meta;
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_batch",meta + "[@@TROVEBBS_DATA@@]" + this.ghRows);
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_progress",meta);
      }
      private function ghTick(e:TimerEvent) : void
      {
         if(this.ghWaiting || this.ghRunning) { this.ghFail("Timeout; try again"); return; }
         if(!this.ghAdvancing) return;
         this.ghAdvancing = false;
         if(this.ghEnd < this.ghTotal - 1) { this.ghStart = this.ghEnd + 1; this.ghRunning = true; this.ghRequest(); return; }
         this.ghStatus.text = "Board " + this.ghBoard + " complete";
         if(this.ghAuto) this.ghNextBoard();
         else this.ghLock(false);
      }
      private function ghNextBoard() : void
      {
         this.ghBoardIndex++; this.ghStart = 0; this.ghRun = ""; this.ghLoadBoard();
      }
      private function ghFail(message:String) : void
      {
         this.ghTimer.reset(); this.ghRunning = false; this.ghWaiting = false; this.ghAdvancing = false; this.ghAuto = false;
         this.ghLock(false); this.ghStatus.text = message;
      }
      private function ghReset(e:MouseEvent) : void
      {
         e.stopPropagation(); this.ghFail("Progress reset"); this.ghProgress = "";
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_progress","");
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","leaderboard_batch","");
         ExternalInterface.call("UIComponent.OnSaveConfig","leaderboard.swf","data","");
      }
      private function ghProgressValue(key:String) : String
      {
         var parts:Array = this.ghProgress.split(";");
         for each(var part:String in parts)
         {
            var split:int = part.indexOf("=");
            if(split > 0 && part.substring(0,split) == key) return part.substring(split + 1);
         }
         return "";
      }


   }
}
